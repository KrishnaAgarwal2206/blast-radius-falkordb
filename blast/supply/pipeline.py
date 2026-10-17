"""End-to-end supply-chain investigation for one app: verdicts -> remediation plan -> checks per candidate -> decision memory.
Heavy steps (building graphs, running venv checks) are cached in data/supply/<app>.json so the live UI stays fast."""
import json
import time
from pathlib import Path

from .. import config
from ..graph.client import db, run
from . import advisories, dists, planner, verify
from .analysis import verdicts
from .apps import APPS
from .build import build, graph_name

OUT = config.ROOT / "data" / "supply"
MEMORY_GRAPH = "sc_memory"


def pins_of(app):
    return dists.parse_pins(Path(APPS[app]["pins"]).read_text())


def prepare(app: str, rebuild=True, run_checks=True, log=print) -> dict:
    """Build the graph, load advisories, compute verdicts + plan, verify each candidate in its own venv, persist decisions."""
    OUT.mkdir(parents=True, exist_ok=True)
    g, pins = graph_name(app), pins_of(app)
    if rebuild:
        build(app, log=log)
        advisories.ingest_advisories(g, pins, log=log)
    v = verdicts(g)
    plan = planner.plan(g, v.data["findings"], pins)
    cands = plan.data["candidates"]
    # the set of packages that must move together: a candidate plus the upgrades that unblocked it
    to_ver = {c["package"]: c["to_version"] for c in cands if c["to_version"]}
    for c in cands:
        if c["to_version"]:
            c["upgrade_set"] = {c["package"]: c["to_version"], **{k: to_ver[k] for k in c.get("unblocked_by", []) if k in to_ver}}
            c["patched_graph"] = f"sc_{app}__up_{c['package']}"
            if rebuild or c["patched_graph"] not in {x for x in __import__("blast.graph.client", fromlist=["list_graphs"]).list_graphs()}:
                log(f"building the upgraded graph {c['patched_graph']} for {c['upgrade_set']}")
                build(app, log=lambda *_: None, pins_override={**pins, **c["upgrade_set"]}, graph=c["patched_graph"])
    prior = load(app)
    checks = dict(prior["checks"]) if (prior and not run_checks) else {}   # --no-checks keeps the previously recorded results
    if run_checks:
        log("running baseline checks")
        checks["baseline"] = verify.run_checks(app, pins, {}, "baseline")
        for c in cands:
            if c["to_version"]:
                log(f"checking {c['package']} {c['from_version']} -> {c['to_version']}")
                checks[c["package"]] = verify.run_checks(app, pins, c["upgrade_set"], f"{c['package']}")
        # the combined plan = every candidate that passes alone (and the pair, to catch interactions)
        ok = {c["package"]: c["to_version"] for c in cands if c["to_version"] and checks.get(c["package"], {}).get("checks") and all(x["ok"] for x in checks[c["package"]]["checks"])}
        if len(ok) > 1:
            checks["combined"] = verify.run_checks(app, pins, ok, "combined")
    snap = dict(app=app, title=APPS[app]["title"], graph=g, ts=int(time.time()), counts=v.data["counts"], total=v.data["total"],
                findings=v.data["findings"], paths=v.paths, plan=cands, checks=checks, pins=pins,
                scanner=dict(total=v.data["total"], high_or_critical=sum(1 for f in v.data["findings"] if f["severity"] in ("HIGH", "CRITICAL"))))
    (OUT / f"{app}.json").write_text(json.dumps(snap, default=str))
    remember(app, snap)
    return snap


def load(app):
    p = OUT / f"{app}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------ persistent decisions (cross-app memory)
def remember(app: str, snap: dict):
    """Write each verdict as a Decision in a shared graph so later investigations (any app) can recall the precedent."""
    for l, p in (("Decision", "id"), ("Vulnerability", "id")):
        try:
            run(MEMORY_GRAPH, f"CREATE INDEX FOR (n:{l}) ON (n.{p})", readonly=False)
        except Exception:
            pass
    for f in snap["findings"]:
        path = snap["paths"][[p["path_id"] for p in snap["paths"]].index(f["path_id"])]["sentence"] if f.get("path_id") and snap["paths"] else ""
        why = {"reachable": f"call path found: {path}",
               "no_path_found": "vulnerable function identified but no call path from an entry point within the analyzed scope (dispatch through class-valued parameters, partials and registered handlers was followed)",
               "unknown": f"vulnerable function could not be identified (fix-diff mapping: {f['mapping']})"}[f["verdict"]]
        run(MEMORY_GRAPH, "MERGE (v:Vulnerability {id:$v}) SET v.package=$p, v.severity=$sev "
                          "MERGE (d:Decision {id:$id}) SET d.app=$app, d.vuln=$v, d.package=$p, d.version=$ver, d.verdict=$vd, d.why=$why, d.ts=$ts, d.source='agent' "
                          "MERGE (d)-[:ABOUT]->(v)",
            {"v": f["id"], "p": f["package"], "sev": f["severity"], "id": f"{app}:{f['id']}", "app": app, "ver": f["version"], "vd": f["verdict"], "why": why[:500], "ts": snap["ts"]},
            readonly=False)


def recall(vuln_ids: list[str], exclude_app: str):
    """Earlier decisions about the same advisories made in OTHER apps."""
    try:
        r = run(MEMORY_GRAPH, "MATCH (d:Decision)-[:ABOUT]->(v:Vulnerability) WHERE v.id IN $ids AND d.app <> $app "
                              "RETURN d.id, d.app, d.vuln, d.package, d.version, d.verdict, d.why, d.ts ORDER BY d.ts DESC",
                {"ids": vuln_ids, "app": exclude_app})
    except Exception:
        return []
    return [dict(zip(["id", "app", "vuln", "package", "version", "verdict", "why", "ts"], row)) for row in r.rows]


if __name__ == "__main__":
    import sys
    snap = prepare(sys.argv[1], rebuild="--no-rebuild" not in sys.argv, run_checks="--no-checks" not in sys.argv)
    print(snap["counts"], snap["scanner"])
    for c in snap["plan"]:
        print(c["package"], c["from_version"], "->", c.get("to_version"), c.get("cleared_in_scope"))
    for k, v in snap["checks"].items():
        print(k, [(x["title"][:28], x["ok"]) for x in v["checks"]], v.get("install_error"))
