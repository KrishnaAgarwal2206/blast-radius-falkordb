"""Reachability verdicts and remediation planning over the supply-chain graph. Deterministic; every result carries its Cypher + latency."""
import math
import re
import time
from dataclasses import dataclass, field

from ..analysis.core import PATH_PROJ, Result, _q, uid
from ..graph.client import run

SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


def cvss3_score(vector: str) -> float | None:
    """CVSS v3.x base score from a vector string (spec formulas)."""
    try:
        m = dict(p.split(":") for p in vector.split("/")[1:])
        av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[m["AV"]]
        ac = {"L": 0.77, "H": 0.44}[m["AC"]]
        scope = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if scope else 0.62, "H": 0.5 if scope else 0.27}[m["PR"]]
        ui = {"N": 0.85, "R": 0.62}[m["UI"]]
        c, i, a = (({"H": 0.56, "L": 0.22, "N": 0}[m[k]]) for k in "CIA")
        iss = 1 - (1 - c) * (1 - i) * (1 - a)
        imp = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope else 6.42 * iss
        expl = 8.22 * av * ac * pr * ui
        if imp <= 0:
            return 0.0
        raw = min((imp + expl) * (1.08 if scope else 1), 10)
        return math.ceil(raw * 10) / 10
    except Exception:
        return None


def band(score):
    return "UNKNOWN" if score is None else "CRITICAL" if score >= 9 else "HIGH" if score >= 7 else "MEDIUM" if score >= 4 else "LOW"


def _possible(res, graph, fns):
    """Shortest path that uses at least one MAYBE_CALLS edge (receiver type unresolved), over all vulnerable functions."""
    best = None
    for fq in fns[:8]:
        r = _q(res, graph, "MATCH (e:Function {entry:true}),(v:Function {qname:$q}) WITH e,v,shortestPath((e)-[:CALLS|MAYBE_CALLS*..25]->(v)) AS p "
                           f"WHERE p IS NOT NULL RETURN length(p), {PATH_PROJ} ORDER BY length(p) LIMIT 1", {"q": fq}, timeout=30000)
        if r.rows and (best is None or r.rows[0][0] < best[0]):
            best = (r.rows[0][0], r.rows[0][1], r.rows[0][2], fq)
    return best


def verdicts(graph: str) -> Result:
    """For every advisory affecting a pinned version: reachable / no path found within analyzed scope / unknown."""
    t0 = time.perf_counter()
    res = Result("reachability")
    vulns = _q(res, graph, "MATCH (s:Service)-[a:AFFECTED_BY]->(x:Vulnerability) OPTIONAL MATCH (x)-[:VULNERABLE_IN]->(f:Function) "
                           "RETURN x.id, s.name, a.version, x.severity, x.cvss, x.summary, x.fixed, x.mapping, collect(f.qname) ORDER BY x.cvss DESC").rows
    out = []
    for vid, pkg, ver, sev, cvss, summ, fixed, mapping, fns in vulns:
        item = dict(id=vid, package=pkg, version=ver, severity=sev, cvss=cvss, summary=summ, fixed=fixed, mapping=mapping, functions=fns)
        best = None
        for fq in fns[:8]:
            r = _q(res, graph, "MATCH (e:Function {entry:true}),(v:Function {qname:$q}) WITH e,v,shortestPath((e)-[:CALLS*..25]->(v)) AS p "
                               f"WHERE p IS NOT NULL RETURN length(p), {PATH_PROJ} ORDER BY length(p) LIMIT 1", {"q": fq}, timeout=30000)
            if r.rows and (best is None or r.rows[0][0] < best[0]):
                best = (r.rows[0][0], r.rows[0][1], r.rows[0][2], fq)
        vuid = uid("Vulnerability", vid)
        res.nodes.setdefault(vuid, dict(label="Vulnerability", key=vid, name=vid))
        if best:
            item["verdict"] = "reachable"
            pairs = [[best[1][i][1], best[1][i + 1][1]] for i in range(len(best[1]) - 1)]
            hw = _q(res, graph, "UNWIND $p AS x MATCH (a:Function {qname:x[0]})-[e:CALLS]->(b:Function {qname:x[1]}) RETURN DISTINCT e.how", {"p": pairs}).rows if pairs else []
            item["via"] = sorted({h[0].split(":")[0] for h in hw if h[0]})
            item["path_id"] = res.add_path(best[1], best[2], pid=f"reach{len(out) + 1}")
            item["hops"] = best[0]
            item["target"] = best[3]
            res.edges.append((vuid, "VULNERABLE_IN", uid("Function", best[3])))
        elif fns and (poss := _possible(res, graph, fns)):
            item["verdict"] = "unknown"
            item["reason"] = "possible_via_dynamic_dispatch"
            item["possible_path_id"] = res.add_path(poss[1], poss[2], pid=f"maybe{len(out) + 1}")
            item["hops"] = poss[0]
            item["target"] = poss[3]
            res.edges.append((vuid, "VULNERABLE_IN", uid("Function", poss[3])))
        elif fns:
            item["verdict"] = "no_path_found"
            # evidence of what the analysis DID reach: the closest function in the same file as the vulnerable one
            r = _q(res, graph, "MATCH (v:Function {qname:$q})<-[:DEFINES]-(f:File)-[:DEFINES]->(s:Function) WHERE s.qname <> $q "
                               "WITH s MATCH (e:Function {entry:true}) WITH e, s, shortestPath((e)-[:CALLS*..25]->(s)) AS p WHERE p IS NOT NULL "
                               f"RETURN length(p), {PATH_PROJ} ORDER BY length(p) LIMIT 1", {"q": fns[0]}, timeout=30000)
            if r.rows:
                item["sibling_path_id"] = res.add_path(r.rows[0][1], r.rows[0][2], pid=f"nopath{len(out) + 1}")
                item["sibling"] = r.rows[0][1][-1][1]
            else:   # the analyzed code never reaches this file at all: that is a blind spot (subprocess, streaming, plugin), not evidence of absence
                item["verdict"] = "unknown"
                item["reason"] = "not_reached"
            res.edges.append((vuid, "VULNERABLE_IN", uid("Function", fns[0])))
            res.nodes.setdefault(uid("Function", fns[0]), dict(label="Function", key=fns[0], name=fns[0]))
        else:
            item["verdict"] = "unknown"
        out.append(item)
    res.data["findings"] = out
    res.data["counts"] = {k: sum(1 for i in out if i["verdict"] == k) for k in ("reachable", "no_path_found", "unknown")}
    res.data["total"] = len(out)
    res.ms = (time.perf_counter() - t0) * 1000
    return res
