"""Supply-chain mode of the agent: tools + the deterministic investigation pipeline that produces Diagnosis / Findings / Actions."""
import difflib
import json
import re

from ..analysis.core import Result, _q, short, uid
from . import pipeline as P
from . import planner
from .analysis import verdicts
from .apps import APPS


def _clean(t: str) -> str:
    """Never leak local filesystem paths into answers."""
    return re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", t or "")


def app_of(graph: str) -> str:
    return graph[3:] if graph.startswith("sc_") else graph


# ------------------------------------------------------------------ tools (each returns a core.Result)
def t_findings(graph, args):
    res = verdicts(graph)
    return res


def t_plan(graph, args):
    app = app_of(graph)
    snap = P.load(app)
    findings = args.get("findings") or (snap or {}).get("findings") or verdicts(graph).data["findings"]
    res = planner.plan(graph, findings, P.pins_of(app), scope=tuple(args.get("scope", ["reachable"])))
    return res


def t_checks(graph, args):
    """Smoke-check results for each upgrade candidate (precomputed in a throw-away venv; see data/supply/<app>.json)."""
    res = Result("sc_checks")
    snap = P.load(app_of(graph))
    res.data["checks"] = (snap or {}).get("checks", {})
    res.data["precomputed_at"] = (snap or {}).get("ts")
    return res


def t_preflight(graph, args):
    """What-if diff in FalkorDB: for each planned upgrade, which names the code imports from the upgraded package no longer exist in the
    upgraded graph? Queries the current graph and the pre-built upgraded graph live, so the Cypher shows in the UI."""
    res = Result("sc_preflight")
    snap = P.load(app_of(graph)) or {}
    out = []
    for c in snap.get("plan", []):
        if not c.get("to_version") or not c.get("patched_graph"):
            continue
        pkg, new_g = c["package"], c["patched_graph"]
        mods = {r[0] for r in _q(res, graph, "MATCH (f:File {service:$p}) RETURN f.module", {"p": pkg}).rows}
        rows = _q(res, graph, "MATCH (f:File) WHERE f.service <> $p AND size(f.imports_from) > 0 RETURN f.path, f.imports_from", {"p": pkg}, timeout=30000).rows
        pairs = []
        for path, imps in rows:
            for imp in imps:
                m, _, n = imp.partition(":")
                if m in mods:
                    pairs.append((path, m, n))
        missing = []
        if pairs:
            uniq = sorted({(m, n) for _p, m, n in pairs})
            r = _q(res, new_g, "UNWIND $pairs AS p OPTIONAL MATCH (f:File {module:p[0]}) OPTIONAL MATCH (g:File {module:p[0] + '.' + p[1]}) "
                               "RETURN p[0], p[1], count(DISTINCT f), sum(CASE WHEN p[1] IN f.names THEN 1 ELSE 0 END), count(DISTINCT g)", {"pairs": [list(x) for x in uniq]}, timeout=30000)
            gone = {(a, b) for a, b, nf, nn, ng in r.rows if (nf == 0 and ng == 0) or (nf > 0 and nn == 0 and ng == 0)}
            missing = [dict(path=p_, file=p_.split("/", 1)[1] if "/" in p_ else p_, module=m, name=n) for p_, m, n in pairs if (m, n) in gone]
        out.append(dict(package=pkg, to_version=c["to_version"], graph=new_g, imports_checked=len(pairs), missing=missing[:8], n_missing=len(missing)))
    res.data["preflight"] = out
    return res


def t_recall(graph, args):
    res = Result("sc_recall")
    app = app_of(graph)
    ids = args.get("vulns", [])
    rows = []
    if ids:
        r = _q(res, P.MEMORY_GRAPH, "MATCH (d:Decision)-[:ABOUT]->(v:Vulnerability) WHERE v.id IN $ids AND d.app <> $app "
                                    "RETURN d.id, d.app, d.vuln, d.package, d.version, d.verdict, d.why, d.ts ORDER BY d.ts DESC", {"ids": ids, "app": app})
        rows = [dict(zip(["id", "app", "vuln", "package", "version", "verdict", "why", "ts"], x)) for x in r.rows]
        for d in rows:
            res.nodes[uid("Decision", d["id"])] = dict(label="Decision", key=d["id"], name=f"{d['app']}: {d['vuln']} -> {d['verdict']}")
    res.data["decisions"] = rows
    return res


# ------------------------------------------------------------------ pipeline
def diff_pins(old: dict, new: dict, cands):
    a = [f"{k}=={v}" for k, v in sorted(old.items())]
    b = [f"{k}=={new.get(k, v)}" for k, v in sorted(old.items())]
    return "".join(difflib.unified_diff([x + "\n" for x in a], [x + "\n" for x in b], "requirements.lock", "requirements.lock (proposed)", n=0))


def pipeline(r, text):
    app = app_of(r.graph)
    spec = APPS[app]
    fr, _ = r.call("sc_findings", {}, "t1")
    if not fr or not fr.data.get("findings"):
        r.send("error", message="No advisories match the pinned versions of this app.", recoverable=False)
        return None
    F = fr.data["findings"]
    reach = [f for f in F if f["verdict"] == "reachable"]
    nopath = [f for f in F if f["verdict"] == "no_path_found"]
    unknown = [f for f in F if f["verdict"] == "unknown"]
    pr, _ = r.call("sc_plan", {"findings": F}, "t2")
    cands = pr.data["candidates"] if pr else []
    fr2, _ = r.call("sc_preflight", {}, "t2b")
    pre = {x["package"]: x for x in (fr2.data["preflight"] if fr2 else [])}
    cr, _ = r.call("sc_checks", {}, "t3")
    checks = cr.data["checks"] if cr else {}
    mr, _ = r.call("sc_recall", {"vulns": [f["id"] for f in reach + nopath]}, "t4")
    decisions = mr.data["decisions"] if mr else []
    pins = P.pins_of(app)
    hc = sum(1 for f in F if f["severity"] in ("HIGH", "CRITICAL"))

    def vnodes(f):
        out = [uid("Vulnerability", f["id"])]
        if f.get("target"):
            out.append(uid("Function", f["target"]))
        return out

    claims, actions = [], []
    claims.append(dict(kind="impact", text=f"{len(F)} advisories match {spec['title']}'s pinned versions ({hc} high/critical): a package-name scanner would flag all of them. "
                                          f"Graph analysis: {len(reach)} reachable from an entry point, {len(nopath)} with no path found in the analyzed scope, {len(unknown)} unknown "
                                          f"(vulnerable function not identified, or only a possible path via unresolved dynamic dispatch: {sum(1 for f in unknown if f.get('possible_path_id'))} of those).",
                       path_ids=[f["path_id"] for f in reach[:3]] or [f["sibling_path_id"] for f in nopath if f.get("sibling_path_id")][:3],
                       node_ids=[uid("Vulnerability", f["id"]) for f in F[:60]]))
    for f in sorted(reach, key=lambda x: -(x["cvss"] or 0))[:4]:
        claims.append(dict(kind="cause", text=f"{f['id']} ({f['package']} {f['version']}, {f['severity']}{', CVSS ' + str(f['cvss']) if f['cvss'] else ''}) is REACHABLE: "
                                              f"{f['hops']} call hops from an entry point to {short('Function:' + f['target'])}, a function changed by the advisory's fix commit.",
                           path_ids=[f["path_id"]], node_ids=vnodes(f)))
    for f in sorted(nopath, key=lambda x: -(x["cvss"] or 0))[:2]:
        if f.get("sibling_path_id"):
            claims.append(dict(kind="similar", text=f"{f['id']} ({f['package']} {f['version']}, {f['severity']}{', CVSS ' + str(f['cvss']) if f['cvss'] else ''}) has NO PATH FOUND within the analyzed scope: "
                                                    f"the app does reach {short('Function:' + f['sibling'])} in the same file, but not the vulnerable {short('Function:' + f['functions'][0])}. "
                                                    f"This is a static-analysis result, not a proof of non-exploitability.",
                               path_ids=[f["sibling_path_id"]], node_ids=[uid("Vulnerability", f["id"])]))
    for f in sorted([x for x in unknown if x.get("possible_path_id")], key=lambda x: -(x["cvss"] or 0))[:2]:
        claims.append(dict(kind="possible", text=f"{f['id']} ({f['package']} {f['version']}, {f['severity']}{', CVSS ' + str(f['cvss']) if f['cvss'] else ''}) is UNKNOWN, with a POSSIBLE path: "
                                               f"{f['hops']} hops to {short('Function:' + f['target'])}, but at least one hop is a dynamic call whose receiver type could not be resolved (MAYBE_CALLS). Review manually.",
                           path_ids=[f["possible_path_id"]], node_ids=[uid("Vulnerability", f["id"])]))
    for d in decisions[:2]:
        mine = next((f for f in F if f["id"] == d["vuln"]), None)
        if mine and mine["verdict"] != d["verdict"] and (mine.get("path_id") or mine.get("sibling_path_id")):
            claims.append(dict(kind="memory", text=f"Memory: {d['vuln']} was previously assessed in {d['app']} ({d['package']} {d['version']}) as '{d['verdict']}'. "
                                                   f"Here it is '{mine['verdict']}': same advisory, different evidence.",
                               path_ids=[mine.get("path_id") or mine["sibling_path_id"]], node_ids=[uid("Vulnerability", d["vuln"])]))
    upgrades = {}
    for c in cands:
        ck = checks.get(c["package"], {})
        passed = bool(ck.get("checks")) and all(x["ok"] for x in ck["checks"])
        failed = [x for x in ck.get("checks", []) if not x["ok"]]
        if c.get("to_version"):
            if passed:
                upgrades[c["package"]] = c["to_version"]
            pf = pre.get(c["package"])
            pf_txt = ((f" Graph preflight: {pf['imports_checked'] - pf['n_missing']}/{pf['imports_checked']} imported names exist in the upgraded graph"
                       + (f"; MISSING {', '.join(m['module'] + '.' + m['name'] for m in pf['missing'][:3])} (imported by {pf['missing'][0]['file']})." if pf["n_missing"] else "."))
                      if pf and pf["imports_checked"] else (f" Graph preflight not evaluated: no code imports names directly from {c['package']} (attribute access is not checked)." if pf else ""))
            vacuous = passed and not any(c["package"] in x.get("exercises", ()) for x in ck.get("checks", []))
            state = ("smoke checks PASS" + (" but they do not exercise this package" if vacuous else "")) if passed else (f"smoke checks FAIL ({_clean(failed[0]['tail'])[:90]})" if failed else "checks not run")
            claims.append(dict(kind="critical", text=f"Upgrade {c['package']} {c['from_version']} -> {c['to_version']} ({c['jump']}) clears {', '.join(c['cleared_in_scope'])} "
                                                     f"(reachable). {c['constraints_checked']} dependent constraint(s) from the graph satisfied{' (together with ' + ', '.join(c['unblocked_by']) + ')' if c.get('unblocked_by') else ''}; {state}.{pf_txt}",
                               path_ids=c["path_ids"][:3], node_ids=[uid("Service", c["package"])] + [uid("Vulnerability", x) for x in c["cleared_in_scope"]]))
        else:
            claims.append(dict(kind="critical", text=f"No installable upgrade for {c['package']} {c['from_version']} clears {', '.join(c['findings'])}: "
                                                     f"{c['blocked'][0][1] if c['blocked'] else 'blocked'}.",
                               path_ids=[f["path_id"] for f in reach if f["package"] == c["package"]][:3], node_ids=[uid("Service", c["package"])]))
    snap_after = (P.load(app) or {}).get("after")
    if snap_after:
        rem = snap_after["reachable"]
        base_paths = [f["path_id"] for f in reach if f["id"] in {x["id"] for x in rem} and f.get("path_id")] or [f["path_id"] for f in reach[:1]]
        claims.append(dict(kind="critical", text=f"Plan outcome (analysis re-run on the upgraded graph with {', '.join(f'{k} {v}' for k, v in snap_after['upgrades'].items())}): "
                                                 f"{snap_after['total']} advisories remain (was {len(F)}), {snap_after['counts']['reachable']} reachable (was {len(reach)})"
                                                 + (f"; still reachable: {', '.join(x['id'] + ' (' + x['package'] + ')' for x in rem)}, which needs a change to the app or a different version." if rem else "."),
                           path_ids=base_paths[:3], node_ids=[uid("Service", k) for k in snap_after["upgrades"]]))
    # ---- actions (drafts; nothing is executed)
    for c in cands:
        ck = checks.get(c["package"], {})
        passed = bool(ck.get("checks")) and all(x["ok"] for x in ck["checks"])
        pids = c.get("path_ids", [])[:3]
        if c.get("to_version") and passed:
            actions.append(dict(kind="mitigate", title=f"Pin {c['package']}=={c['to_version']}", detail=f"Clears {', '.join(c['cleared_in_scope'])}. Smoke checks passed in a throw-away venv ({len(ck['checks'])}/{len(ck['checks'])}); this is not the app's full test suite.",
                                command=f"pip install {c['package']}=={c['to_version']}", path_ids=pids, risk=f"{c['jump']} version bump"))
        elif c.get("to_version"):
            fail = next((x for x in ck.get("checks", []) if not x["ok"]), None)
            actions.append(dict(kind="review", title=f"Do NOT pin {c['package']}=={c['to_version']} yet", detail=f"It would clear {', '.join(c['cleared_in_scope'])} but the app's smoke checks fail: {_clean(fail['tail'])[:140] if fail else 'not run'}. "
                                                                                                                   f"Needs an app change (upgrade the app or patch its use of {c['package']}).", path_ids=pids, risk="breaks the app as pinned"))
    if upgrades:
        patch = diff_pins(pins, upgrades, cands)
        top = next((f for f in reach if f["package"] in upgrades), reach[0] if reach else None)
        actions.append(dict(kind="inspect", title="Proposed lockfile change (unified diff)", detail=patch, command="git apply requirements.patch", path_ids=[top["path_id"]] if top and top.get("path_id") else [], risk="draft; review before applying"))
        ids = [x for c in cands if c["package"] in upgrades for x in c["cleared_in_scope"]]
        actions.append(dict(kind="message", title="Draft pull request description",
                            detail=f"Security: bump {', '.join(f'{k} to {v}' for k, v in upgrades.items())}. Clears reachable advisories {', '.join(ids)}. Evidence: call path(s) from an application entry point to the advisory's vulnerable function (see linked graph paths). "
                                   f"Checked: app smoke checks pass on the proposed pins. Not checked: the full test suite. Out of scope: {len(nopath)} advisories with no path found and {len(unknown)} unknown.",
                            path_ids=[next(f for f in reach if f["id"] in ids)["path_id"]] if ids else [], risk="none"))
    fixes = (P.load(app) or {}).get("app_patches", {})
    af = (P.load(app) or {}).get("after_fixed")
    for pkg, fx in fixes.items():
        cand = next((c for c in cands if c["package"] == pkg), None)
        if not cand or not fx.get("passed"):
            continue
        pids = cand.get("path_ids", [])[:3]
        extra = ", ".join(f"{k} {v}" for k, v in fx["extra_upgrades"].items())
        claims.append(dict(kind="critical", text=f"Verified fix path for {pkg} {cand['to_version']}: the graph preflight found names removed in the upgraded graph; "
                                                 f"the plan adds {extra or 'no extra upgrade'}{' and ' if extra and fx['files'] else ''}{'a patch to ' + ', '.join(fx['files']) if fx['files'] else ''}; "
                                                 f"smoke checks PASS on that combination ({len(fx['checks'])}/{len(fx['checks'])})."
                                                 + (f" Re-analysis with everything applied: {af['counts']['reachable']} reachable advisories remain (was {len(reach)})." if af else ""),
                           path_ids=pids, node_ids=[uid("Service", pkg)] + [uid("Vulnerability", x) for x in cand["cleared_in_scope"]]))
        actions.append(dict(kind="mitigate", title=f"Proposed fix for the blocked {pkg} upgrade (LLM-authored patch + extra upgrade, verified by smoke checks only)",
                            detail=(("Pin " + ", ".join(f"{k}=={v}" for k, v in fx["upgrades"].items()) + ". ") + ("Apply the patch below to " + ", ".join(fx["files"]) + ":\n" + fx["diff"] if fx["diff"] else "")),
                            command=f"pip install {' '.join(f'{k}=={v}' for k, v in fx['upgrades'].items())}", path_ids=pids, risk="draft: review the patch" + ("; " + "; ".join(fx.get("warnings", [])) if fx.get("warnings") else "") + "; smoke checks are not the full test suite"))
    for f in sorted(nopath, key=lambda x: -(x["cvss"] or 0))[:2]:
        if f.get("sibling_path_id"):
            actions.append(dict(kind="notify", title=f"Draft VEX statement for {f['id']} (under_investigation, static evidence attached)",
                                detail=json.dumps(dict(vulnerability=f["id"], product=spec["title"], status="under_investigation", proposed_status="not_affected",
                                                       proposed_justification="vulnerable_code_not_in_execute_path",
                                                       basis="static call-graph analysis found no path from entry points to the vulnerable function; requires human or runtime confirmation before it can be asserted",
                                                       analyzed_by="Blast Radius")),
                                path_ids=[f["sibling_path_id"]], node_ids=[uid("Vulnerability", f["id"])], risk="static analysis only: do not publish as not_affected without confirmation"))
    for f in sorted(unknown, key=lambda x: -(x["cvss"] or 0))[:2]:
        pass
    top_unknown = sorted(unknown, key=lambda x: -(x["cvss"] or 0))[:1]
    for f in top_unknown:
        why = {"possible_via_dynamic_dispatch": "a possible path exists only through unresolved dynamic dispatch (MAYBE_CALLS).",
               "not_reached": "the analyzed code never reaches the file that contains it (it may be used through a subprocess, streaming or plugin mechanism we cannot see)."}.get(f.get("reason"), "the advisory's fix commit does not point to a Python function we can locate (for example shell templates or data files).")
        actions.append(dict(kind="review", title=f"Manually review {f['id']} ({f['package']} {f['version']}, {f['severity']})", detail=f"Reachability is UNKNOWN, not safe: {why}",
                            path_ids=[p for p in [f.get("possible_path_id")] if p], node_ids=[uid("Vulnerability", f["id"])], risk="unknown"))
    try:                      # the investigation itself writes its verdicts to the shared decision graph (Portfolio and later runs read them)
        P.remember(app, dict(findings=F, paths=fr.paths, ts=int(__import__("time").time())))
    except Exception:
        pass
    m = re.search(r"CVE-\d{4}-\d+", text or "", re.I)
    focus = m.group(0).upper() if m else None
    if focus:
        if not any(f["id"] == focus for f in F):
            r.send("error", message=f"{focus} is not among the {len(F)} advisories matching {spec['title']}'s pinned versions.", recoverable=False)
            return None
        ff = next(f for f in F if f["id"] == focus)
        claims = [c for c in claims if focus in c["text"] or (c["kind"] == "critical" and c["text"].startswith(f"Upgrade {ff['package']} "))] or claims[:1]
        actions = [a for a in actions if focus in (a["title"] + a["detail"] + a.get("command", "")) or ff["package"] in (a["title"] + a.get("command", ""))]
        if not claims or focus not in " ".join(c["text"] for c in claims):
            claims.insert(0, dict(kind="impact", text=f"{focus} ({ff['package']} {ff['version']}, {ff['severity']}) verdict: {ff['verdict'].replace('_', ' ')}"
                                                      + (f" ({ff['reason'].replace('_', ' ')})" if ff.get("reason") else "") + f"; fixed in {', '.join(ff['fixed'][:2]) or 'n/a'}.",
                                  path_ids=[p for p in [ff.get("path_id") or ff.get("possible_path_id") or ff.get("sibling_path_id")] if p], node_ids=[uid("Vulnerability", focus)]))
            if not claims[0]["path_ids"]:
                claims[0]["path_ids"] = [f["path_id"] for f in reach[:1]] or [f["sibling_path_id"] for f in nopath[:1]]
    ans = dict(summary=(f"Focus {focus}: " if focus else "") + f"{spec['title']}: scanner view {len(F)} advisories ({hc} high/critical). Graph view: {len(reach)} reachable, {len(nopath)} no path found, {len(unknown)} unknown. "
                       f"{len(upgrades)} upgrade(s) pass smoke checks and clear {sum(len(c['cleared_in_scope']) for c in cands if c['package'] in upgrades)} reachable finding(s).",
               confidence=0.6, claims=claims, actions=actions,
               extras=dict(app=app, title=spec["title"], scanner=dict(total=len(F), high_or_critical=hc), counts=dict(reachable=len(reach), no_path_found=len(nopath), unknown=len(unknown)),
                           findings=[dict(id=f["id"], package=f["package"], version=f["version"], severity=f["severity"], cvss=f["cvss"], verdict=f["verdict"], reason=f.get("reason"), fixed=f["fixed"][:2],
                                          function=((f.get("target") or (f["functions"][0] if f["functions"] else "")).split(".")[-1] or None), mapping=f["mapping"], hops=f.get("hops"),
                                          path_id=f.get("path_id") or f.get("possible_path_id") or f.get("sibling_path_id")) for f in sorted(F, key=lambda x: (["reachable", "no_path_found", "unknown"].index(x["verdict"]), -(x["cvss"] or 0)))],
                           checks={k: dict(ok=bool(v.get("checks")) and all(c["ok"] for c in v["checks"]), install_ok=v.get("install_ok"), install_error=_clean(v.get("install_error") or ""),
                                           checks=[dict(title=c["title"], ok=c["ok"], tail=_clean(c["tail"])[:160], exercises=c.get("exercises")) for c in v.get("checks", [])]) for k, v in checks.items()},
                           precomputed_at=cr.data.get("precomputed_at") if cr else None))
    return ans, [], []
