"""Close the loop when an upgrade is blocked because something imports a name that no longer exists in the upgraded graph.
1. diff the imports of the current graph against an upgraded graph (FalkorDB);
2. a missing name in another DEPENDENCY -> add the newest installable version of that dependency that its dependents allow, rebuild, diff again;
3. a missing name in the APP's own code -> ask the LLM for the smallest patch, apply it to a COPY of the app;
4. run the same smoke checks on (upgrades + patched copy).
The result is a proposal with evidence; nothing is applied to the real repo. Run: python -m blast.supply.appfix <app>"""
import difflib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from packaging.specifiers import SpecifierSet

from .. import config
from ..graph.client import run
from . import pipeline as P
from . import planner, verify
from .apps import APPS
from .build import build


def diff_imports(old_g, new_g, pkgs, app):
    """Names that code (outside the upgraded packages) imports from the upgraded packages and that are missing in the upgraded graph."""
    mods = {}
    for p in pkgs:
        for (m,) in run(old_g, "MATCH (f:File {service:$p}) RETURN f.module", {"p": p}).rows:
            mods[m] = p
    rows = run(old_g, "MATCH (f:File) WHERE NOT f.service IN $pk AND size(f.imports_from) > 0 RETURN f.path, f.imports_from", {"pk": list(pkgs)}, timeout=30000).rows
    pairs = [(path, m, imp.partition(":")[2]) for path, imps in rows for imp in imps for m in [imp.partition(":")[0]] if m in mods]
    if not pairs:
        return []
    uniq = sorted({(m, n) for _p, m, n in pairs})
    r = run(new_g, "UNWIND $pairs AS p OPTIONAL MATCH (f:File {module:p[0]}) OPTIONAL MATCH (g:File {module:p[0] + '.' + p[1]}) "
                   "RETURN p[0], p[1], count(DISTINCT f), sum(CASE WHEN p[1] IN f.names THEN 1 ELSE 0 END), count(DISTINCT g)", {"pairs": [list(x) for x in uniq]}, timeout=30000)
    gone = {(a, b) for a, b, nf, nn, ng in r.rows if (nf == 0 and ng == 0) or (nf > 0 and nn == 0 and ng == 0)}
    return [dict(path=p_, module=m, name=n, owner=p_.split("@")[0] if "@" in p_.split("/")[0] else app) for p_, m, n in pairs if (m, n) in gone]


def _llm_patch(path, source, error, pkg, ver):
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=config.AGENT_MODEL, max_tokens=3000,
        system="You make the smallest possible compatibility fix to a Python source file. Output ONLY the complete updated file in one ```python block. Change nothing else.",
        messages=[{"role": "user", "content": f"The app must keep working after upgrading {pkg} to {ver}. Static analysis says this file imports a name that no longer exists:\n{error}\n\nFile `{path}`:\n```python\n{source}\n```"}])
    m = re.search(r"```python\n(.*?)```", msg.content[0].text, re.S)
    return (m.group(1) if m else None), (msg.usage.input_tokens * 1.0 + msg.usage.output_tokens * 5.0) / 1e6


def _newest_allowed(g, pkg2):
    cons = run(g, "MATCH (d:Service)-[e:DEPENDS_ON]->(p:Service {name:$p}) RETURN d.name, e.spec", {"p": pkg2}).rows
    best = None
    for v, installable in planner.pypi_versions(pkg2):
        if installable and all(not sp or v in SpecifierSet(sp) for _d, sp in cons):
            best = v
    return str(best) if best else None


def run_app(app: str, log=print):
    snap = P.load(app)
    spec = APPS[app]
    g, pins = snap["graph"], snap["pins"]
    out, cost = {}, 0.0
    for c in snap["plan"]:
        pkg = c["package"]
        ck = snap["checks"].get(pkg, {})
        if not (c.get("to_version") and ck.get("checks") and not all(x["ok"] for x in ck["checks"])):
            continue
        ups = dict(c["upgrade_set"])
        steps, overlay, diff_txt = [], {}, ""
        for rnd in range(3):
            ng = f"sc_{app}__fix_{pkg}"
            build(app, log=lambda *_: None, pins_override={**pins, **ups}, graph=ng)
            miss = diff_imports(g, ng, list(ups), app)
            deps = sorted({m["owner"] for m in miss if m["owner"] != app and m["owner"] not in ups})
            mine = [m for m in miss if m["owner"] == app]
            steps.append(dict(round=rnd + 1, upgrades=dict(ups), missing=[f"{m['module']}.{m['name']} (imported by {m['path'].split('/', 1)[-1]})" for m in miss[:6]]))
            if deps:
                for d in deps:
                    v = _newest_allowed(g, d)
                    if v and v != pins.get(d):
                        ups[d] = v
                        log(f"{pkg}: {d} imports a removed name -> also upgrade {d} to {v}")
                continue
            if mine and not overlay:
                rel = mine[0]["path"].split("/", 1)[1]
                src = (Path(spec["repo"]) / rel).read_text(encoding="utf-8")
                err = "\n".join(f"- `{m['module']}.{m['name']}` no longer exists in the upgraded graph" for m in mine if m["path"] == mine[0]["path"])
                new_src, cst = _llm_patch(rel, src, err, pkg, ups[pkg])
                cost += cst
                if new_src:
                    overlay[rel] = new_src
                    diff_txt = "".join(difflib.unified_diff(src.splitlines(True), new_src.splitlines(True), f"a/{rel}", f"b/{rel}", n=2))
                    log(f"{pkg}: LLM proposed a patch to {rel}")
            break
        tmp = Path(tempfile.mkdtemp(prefix="appfix-", dir=str(config.ROOT / "data" / "envs")))
        try:
            shutil.copytree(spec["repo"], tmp / "app", ignore=shutil.ignore_patterns("__pycache__", ".git", "tests", "docs"))
            for rel, text in overlay.items():
                (tmp / "app" / rel).write_text(text, encoding="utf-8")
            verify.APPS[app] = dict(spec, repo=str(tmp / "app"))
            res = verify.run_checks(app, pins, ups, f"{pkg}-fixed")
        finally:
            verify.APPS[app] = spec
            shutil.rmtree(tmp, ignore_errors=True)
        passed = bool(res.get("checks")) and all(x["ok"] for x in res["checks"])
        log(f"{pkg}: upgrades {ups} + app patch {'yes' if overlay else 'no'} -> checks {'PASS' if passed else 'FAIL'}")
        out[pkg] = dict(upgrades=ups, extra_upgrades={k: v for k, v in ups.items() if k not in c["upgrade_set"]}, files=list(overlay), diff=diff_txt, steps=steps,
                        checks=res.get("checks", []), passed=passed, model=config.AGENT_MODEL if overlay else None, cost_usd=round(cost, 4))
    snap["app_patches"] = out
    good = {k: v for k, v in out.items() if v["passed"]}
    if good:
        full = dict(snap["after"]["upgrades"]) if snap.get("after") else {}
        for v in good.values():
            full.update(v["upgrades"])
        from . import advisories
        from .analysis import verdicts
        ag = f"sc_{app}__up_fixed"
        build(app, log=lambda *_: None, pins_override={**pins, **full}, graph=ag)
        advisories.ingest_advisories(ag, {**pins, **full}, log=lambda *_: None)
        va = verdicts(ag)
        snap["after_fixed"] = dict(graph=ag, upgrades=full, counts=va.data["counts"], total=va.data["total"],
                                   reachable=[dict(id=f["id"], package=f["package"]) for f in va.data["findings"] if f["verdict"] == "reachable"])
    (P.OUT / f"{app}.json").write_text(json.dumps(snap, default=str))
    if cost:
        try:
            from ..agent.loop import add_spend
            add_spend(cost)
        except Exception:
            pass
    return out


if __name__ == "__main__":
    print({k: (v["passed"], v["extra_upgrades"], v["files"]) for k, v in run_app(sys.argv[1]).items()})
