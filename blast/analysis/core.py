"""L3 deterministic graph intelligence. No LLM. Each function returns a Result carrying
nodes, edges, evidence paths, and the exact Cypher it ran (with server latency)."""
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from ..graph.client import run, track

PATH_PROJ = ("[n IN nodes(p) | [labels(n)[0], coalesce(n.path,n.qname,n.sha,n.email,n.id,n.name), "
             "coalesce(n.msg,n.title,n.name,n.qname,n.path,n.email)]] AS ns, [r IN relationships(p) | type(r)] AS rs")
KEYS = {"File": "path", "Function": "qname", "Service": "name", "Commit": "sha", "Person": "email",
        "Incident": "id", "Class": "qname", "Package": "name", "Repo": "name"}


def uid(label, key):
    return f"{label}:{key}"


def short(u: str) -> str:
    label, _, key = u.partition(":")
    if label == "File":
        return key.split("/src/")[-1]
    if label == "Commit":
        return key[:8]
    return key


@dataclass
class Result:
    tool: str
    data: dict = field(default_factory=dict)
    nodes: dict = field(default_factory=dict)     # uid -> {label,key,name}
    edges: list = field(default_factory=list)     # (src_uid, type, dst_uid)
    paths: list = field(default_factory=list)     # {path_id, nodes[], rels[], sentence}
    queries: list = field(default_factory=list)   # QResult
    ms: float = 0.0

    def add_path(self, ns, rs, pid=None, prefix="p"):
        pid = pid or f"{prefix}{len(self.paths) + 1}"
        us = [uid(l, k) for l, k, _ in ns]
        for (l, k, d), u in zip(ns, us):
            self.nodes.setdefault(u, dict(label=l, key=k, name=d))
        for i, r in enumerate(rs):
            self.edges.append((us[i], r, us[i + 1]))
        nm = [d if l == "Person" and d else short(u) for (l, _, d), u in zip(ns, us)]
        sent = nm[0] + "".join(f" —{r}→ {nm[i + 1]}" for i, r in enumerate(rs))
        self.paths.append(dict(path_id=pid, nodes=us, rels=rs, sentence=sent))
        return pid

    def summary(self):
        return {"tool": self.tool, **self.data}


def _q(res: Result, graph, cypher, params=None, timeout=8000):
    r = run(graph, cypher, params or {}, timeout=timeout)
    res.queries.append(r)
    return r


def snapshot_time(graph) -> int:
    """'Now' for recency scoring = newest commit in the graph (a snapshot), so results are reproducible."""
    return run(graph, "MATCH (c:Commit) RETURN max(c.ts)").rows[0][0] or int(time.time())


# ---------------------------------------------------------------- target resolution
def resolve_target(graph, text: str, res: Result | None = None, strict: bool = False):
    """Map free text to (label, key). Tries Service, File, Function in that order."""
    text = text.strip().strip("`'\"")
    res = res or Result("resolve")
    for q, label, params in [
        ("MATCH (n:Service) WHERE (n.name = $t OR n.name = ('opentelemetry-' + $t) OR n.dir = $t) RETURN n.name", "Service", {"t": text}),
        ("MATCH (n:File) WHERE (n.path = $t OR n.path ENDS WITH $t) RETURN n.path ORDER BY size(n.path) LIMIT 1", "File", {"t": text}),
        ("MATCH (n:Function) WHERE (n.qname = $t OR n.qname ENDS WITH ('.' + $t)) RETURN n.qname ORDER BY size(n.qname) LIMIT 1", "Function", {"t": text}),
        ("MATCH (c:Class) WHERE (c.qname = $t OR c.qname ENDS WITH ('.' + $t)) RETURN c.file ORDER BY size(c.qname) LIMIT 1", "File", {"t": text}),
        ("MATCH (n:Service) WHERE n.name CONTAINS $t RETURN n.name ORDER BY size(n.name) LIMIT 1", "Service", {"t": text.lower()}),
        ("MATCH (n:File) WHERE n.path CONTAINS $t RETURN n.path ORDER BY size(n.path) LIMIT 1", "File", {"t": text}),
    ][: 4 if strict else 6]:
        r = _q(res, graph, q, params)
        if r.rows:
            return label, r.rows[0][0]
    return None, None


# ---------------------------------------------------------------- blast radius
def blast_radius(graph, target: str, max_depth: int = 3) -> Result:
    t0 = time.perf_counter()
    res = Result("blast_radius")
    with_track = track()
    label, key = resolve_target(graph, target, res)
    if not label:
        res.data = {"error": f"no Service/File/Function matches '{target}'"}
        return res
    res.data["target"] = uid(label, key)
    impacted = {}  # uid -> (depth, path_id)

    def collect(cypher, params, tail=None):
        for ns, rs in _q(res, graph, cypher, params).rows:
            u = uid(*ns[0][:2])
            if tail:   # extend the path so it really ends at the failing node (e.g. File -DEFINES-> Function)
                ns, rs = ns + tail[0], rs + tail[1]
            d = len(rs)
            if u not in impacted or impacted[u][0] > d:
                impacted[u] = (d, ns, rs)

    d = int(max_depth)
    if label == "File":
        collect(f"MATCH p=(x:File)-[:IMPORTS*1..{d}]->(t:File {{path:$k}}) RETURN {PATH_PROJ} LIMIT 400", {"k": key})
        svc = _q(res, graph, "MATCH (s:Service)-[:CONTAINS]->(f:File {path:$k}) RETURN s.name", {"k": key}).rows
        if svc:
            collect(f"MATCH p=(x:Service)-[:DEPENDS_ON*1..{d}]->(t:Service {{name:$k}}) RETURN {PATH_PROJ} LIMIT 200", {"k": svc[0][0]})
            res.data["service"] = uid("Service", svc[0][0])
    elif label == "Function":
        collect(f"MATCH p=(x:Function)-[:CALLS*1..{d}]->(t:Function {{qname:$k}}) RETURN {PATH_PROJ} LIMIT 400", {"k": key})
        f = _q(res, graph, "MATCH (s:Service)-[:CONTAINS]->(f:File)-[:DEFINES]->(:Function {qname:$k}) RETURN f.path, s.name", {"k": key}).rows
        if f:
            fn_node = ["Function", key, key]
            collect(f"MATCH p=(x:File)-[:IMPORTS*1..{d}]->(t:File {{path:$k}}) RETURN {PATH_PROJ} LIMIT 300", {"k": f[0][0]}, ([fn_node], ["DEFINES"]))
            collect(f"MATCH p=(x:Service)-[:DEPENDS_ON*1..{d}]->(t:Service {{name:$k}}) RETURN {PATH_PROJ} LIMIT 200", {"k": f[0][1]},
                    ([["File", f[0][0], f[0][0]], fn_node], ["CONTAINS", "DEFINES"]))
            res.data["service"] = uid("Service", f[0][1])
    else:
        collect(f"MATCH p=(x:Service)-[:DEPENDS_ON*1..{d}]->(t:Service {{name:$k}}) RETURN {PATH_PROJ} LIMIT 300", {"k": key})
    ranked = sorted(impacted.items(), key=lambda kv: (kv[1][0], kv[0]))
    items = []
    for u, (dep, ns, rs) in ranked[:60]:
        pid = res.add_path(ns, rs, pid=f"impact{len(items) + 1}")
        items.append(dict(uid=u, label=u.split(":")[0], depth=dep, path_id=pid))
    res.data["impacted"] = items
    res.data["counts"] = {l: sum(1 for i in impacted if i.startswith(l + ":")) for l in ("Service", "File", "Function")}
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- stack trace
NOISY_MSG = re.compile(r"(line length|reformat|formatting|\blint|ruff|black\b|isort|pre-commit|typo|annotation|docstring|return type|typing|type hint|mypy|pyright|pylint|docs?:|documentation|changelog|bump|dependabot|renovate|\bci\b|workflow)", re.I)
FRAME = re.compile(r'File "([^"]+)", line (\d+), in ([\w<>]+)')


def trace_stacktrace(graph, text: str) -> Result:
    t0 = time.perf_counter()
    res = Result("trace_stacktrace")
    track()
    frames = [(p.replace("\\", "/"), int(l), fn) for p, l, fn in FRAME.findall(text or "")]
    res.data["frames_parsed"] = len(frames)
    if not frames:
        res.data["error"] = "no Python frames ('File \"...\", line N, in fn') found in input"
        return res
    mapped = []
    for path, line, fname in frames:
        m = re.search(r"(?:site-packages|src)/(.+)$", path)
        if not m:
            continue
        suffix = "/src/" + m.group(1) if "src/" in path and "site-packages" not in path else m.group(1)
        r = _q(res, graph, "MATCH (f:File) WHERE f.path ENDS WITH $s RETURN f.path ORDER BY size(f.path) LIMIT 1", {"s": m.group(1)})
        if not r.rows:
            continue
        fpath = r.rows[0][0]
        fr = _q(res, graph, "MATCH (f:File {path:$p})-[:DEFINES]->(fn:Function) WHERE fn.start <= $l AND fn.end >= $l "
                            "RETURN fn.qname ORDER BY fn.end - fn.start LIMIT 1", {"p": fpath, "l": line})
        fq = fr.rows[0][0] if fr.rows else None
        mapped.append(dict(file=uid("File", fpath), function=uid("Function", fq) if fq else None, line=line, name=fname))
        res.nodes.setdefault(uid("File", fpath), dict(label="File", key=fpath, name=fpath))
        if fq:
            res.nodes.setdefault(uid("Function", fq), dict(label="Function", key=fq, name=fq))
            res.edges.append((uid("File", fpath), "DEFINES", uid("Function", fq)))
    res.data["frames"] = mapped
    res.data["in_repo_frames"] = len(mapped)
    if not mapped:
        res.data["error"] = "frames parsed but none map to files in this graph (third-party or wrong repo?)"
        return res
    res.data["origin"] = (mapped[-1]["function"] or mapped[-1]["file"])
    res.data["origin_file"] = mapped[-1]["file"]
    fns = [m["function"] for m in mapped if m["function"]]
    for i in range(len(fns) - 1):
        a, b = fns[i].split(":", 1)[1], fns[i + 1].split(":", 1)[1]
        r = _q(res, graph, f"MATCH (a:Function {{qname:$a}}),(b:Function {{qname:$b}}) "
                           f"WITH shortestPath((a)-[:CALLS*..4]->(b)) AS p WHERE p IS NOT NULL RETURN {PATH_PROJ}", {"a": a, "b": b})
        for ns, rs in r.rows:
            res.add_path(ns, rs, pid=f"frame{i + 1}")
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- suspects
def suspect_changes(graph, node_uids: list[str], window_days: int = 120, top: int = 5, focus: list[str] | None = None) -> Result:
    """Rank commits touching the impacted subgraph by recency x churn x proximity.
    `focus` = the failing node(s) (origin of a stack trace); other seeds (caller frames) count for far less."""
    t0 = time.perf_counter()
    res = Result("suspect_changes")
    track()
    files = [u.split(":", 1)[1] for u in node_uids if u.startswith("File:")]
    funcs = [u.split(":", 1)[1] for u in node_uids if u.startswith("Function:")]
    svcs = [u.split(":", 1)[1] for u in node_uids if u.startswith("Service:")]
    now = snapshot_time(graph)
    res.data["reference_time"] = now
    rows = []  # (hop_weight, relation, commit row, target uid, path)
    if funcs:
        r = _q(res, graph, f"MATCH p=(c:Commit)-[m:MODIFIED]->(t:Function) WHERE t.qname IN $k AND c.ts >= $since "
                           f"RETURN c.sha, c.msg, c.ts, m.adds, m.dels, {PATH_PROJ}", {"k": funcs, "since": now - window_days * 86400})
        rows += [(1.0, "function", x) for x in r.rows]
        r = _q(res, graph, f"MATCH (f:File)-[:DEFINES]->(t:Function) WHERE t.qname IN $k "
                           f"MATCH p=(c:Commit)-[m:MODIFIED]->(f) WHERE c.ts >= $since "
                           f"RETURN c.sha, c.msg, c.ts, m.adds, m.dels, {PATH_PROJ}", {"k": funcs, "since": now - window_days * 86400})
        rows += [(0.7, "file", x) for x in r.rows]
    if files:
        r = _q(res, graph, f"MATCH p=(c:Commit)-[m:MODIFIED]->(t:File) WHERE t.path IN $k AND c.ts >= $since "
                           f"RETURN c.sha, c.msg, c.ts, m.adds, m.dels, {PATH_PROJ}", {"k": files, "since": now - window_days * 86400})
        rows += [(0.9, "file", x) for x in r.rows]
        r = _q(res, graph, f"MATCH (o:File)-[:IMPORTS]->(d:File) WHERE o.path IN $k "
                           f"MATCH p=(c:Commit)-[m:MODIFIED]->(d) WHERE c.ts >= $since AND NOT d.path IN $k "
                           f"RETURN c.sha, c.msg, c.ts, m.adds, m.dels, {PATH_PROJ}", {"k": files, "since": now - window_days * 86400})
        rows += [(0.12, "dependency", x) for x in r.rows]
    if svcs:
        r = _q(res, graph, f"MATCH (s:Service)-[:CONTAINS]->(t:File) WHERE s.name IN $k "
                           f"MATCH p=(c:Commit)-[m:MODIFIED]->(t) WHERE c.ts >= $since "
                           f"RETURN c.sha, c.msg, c.ts, m.adds, m.dels, {PATH_PROJ}", {"k": svcs, "since": now - window_days * 86400})
        rows += [(0.35, "service", x) for x in r.rows]
    best = {}
    for w, rel, (sha, msg, ts, adds, dels, ns, rs) in rows:
        age = (now - ts) / 86400
        tgt = uid(*ns[-1][:2])
        caller = bool(focus) and rel in ("function", "file") and tgt not in focus
        score = w * (0.2 if caller else 1.0) * math.exp(-math.log(2) * age / 30) * (1 + math.log1p((adds or 0) + (dels or 0)))
        if NOISY_MSG.search(msg or ""):
            score *= 0.15   # formatting / lint / typing / docs churn is rarely the cause of an incident
        tier = {"function": 0, "file": 1}.get("caller" if caller else rel, 2)
        if sha not in best or (tier, -score) < (best[sha]["tier"], -best[sha]["score"]):
            best[sha] = dict(tier=tier, sha=sha, msg=msg, age_days=round(age, 1), score=round(score, 3), via=("caller" if caller else rel), ns=ns, rs=rs)
    out = []
    # commits that touched the failing frame itself always outrank commits that only touched callers/dependencies
    ranked = sorted(best.values(), key=lambda x: ({"function": 0, "file": 1}.get(x["via"], 2), -x["score"]))
    quiet = [b for b in ranked if not NOISY_MSG.search(b["msg"] or "")]
    if quiet:   # formatting/lint/typing churn only survives when nothing else touched the code
        ranked = quiet
    direct = [b for b in ranked if b["via"] in ("function", "file", "caller")]
    if len(direct) >= 3:   # enough direct evidence: ignore commits that only touched a dependency
        ranked = direct
    for b in ranked[:top]:
        b.pop("tier", None)
        b["reason"] = {"function": "wrote lines of the failing function (git blame)", "file": "edited the failing file", "dependency": "edited a file the failing code imports",
                       "service": "edited another file in the same package", "caller": "edited a caller higher in the stack trace (not the failing frame)"}[b["via"]]
        pid = res.add_path(b.pop("ns"), b.pop("rs"), pid=f"suspect{len(out) + 1}")
        out.append(dict(b, uid=uid("Commit", b["sha"]), path_id=pid))
    res.data["suspects"] = out
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- who to page
def who_to_page(graph, node_uids: list[str], suspect_shas: list[str] | None = None) -> Result:
    t0 = time.perf_counter()
    res = Result("who_to_page")
    track()
    now = snapshot_time(graph)
    files = [u.split(":", 1)[1] for u in node_uids if u.startswith("File:")]
    svcs = {u.split(":", 1)[1] for u in node_uids if u.startswith("Service:")}
    if files:
        r = _q(res, graph, "MATCH (s:Service)-[:CONTAINS]->(f:File) WHERE f.path IN $k RETURN DISTINCT s.name", {"k": files})
        svcs |= {x[0] for x in r.rows}
    people = defaultdict(lambda: dict(score=0.0, reasons=[], paths=[]))
    for owner_q, params, w in [
        (f"MATCH p=(x:Person)-[o:OWNS]->(t:Service) WHERE t.name IN $k AND coalesce(x.bot,false)=false RETURN x.email, x.name, o.score, {PATH_PROJ}", {"k": list(svcs)}, 0.5),
        (f"MATCH p=(x:Person)-[o:OWNS]->(t:File) WHERE t.path IN $k AND coalesce(x.bot,false)=false RETURN x.email, x.name, o.score, {PATH_PROJ}", {"k": files}, 0.5),
    ]:
        if not params["k"]:
            continue
        for email, name, sc, ns, rs in _q(res, graph, owner_q, params).rows:
            p = people[email]
            p["name"] = name
            p["score"] += w * (sc or 0)
            p["reasons"].append(f"owns {short(uid(*ns[-1][:2]))} (inferred {sc})")
            p["paths"].append((ns, rs))
    if suspect_shas:
        r = _q(res, graph, f"MATCH p=(x:Person)-[:AUTHORED]->(c:Commit) WHERE c.sha IN $k AND coalesce(x.bot,false)=false "
                           f"RETURN x.email, x.name, {PATH_PROJ}", {"k": suspect_shas})
        for email, name, ns, rs in r.rows:
            p = people[email]
            p["name"] = name
            p["score"] += 0.6
            p["reasons"].append(f"authored suspect commit {ns[-1][1][:8]}")
            p["paths"].append((ns, rs))
    r = _q(res, graph, "MATCH (x:Person)-[:AUTHORED]->(c:Commit) WHERE x.email IN $k RETURN x.email, max(c.ts)", {"k": list(people)}) if people else None
    last = dict(r.rows) if r else {}
    out = []
    for email, p in sorted(people.items(), key=lambda kv: -kv[1]["score"])[:4]:
        inactive = (now - last.get(email, 0)) / 86400 > 90
        pids = [res.add_path(ns, rs, pid=f"page{len(out) + 1}_{k + 1}") for k, (ns, rs) in enumerate(p["paths"][:3])]
        out.append(dict(email=email, name=p["name"], score=round(p["score"], 3), why="; ".join(p["reasons"][:3]),
                        inactive=inactive, path_id=pids[0], path_ids=pids, uid=uid("Person", email)))
    res.data["page"] = out
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- criticality
_crit_cache: dict = {}


def critical_nodes(graph, scope: str = "Service", top: int = 8) -> Result:
    t0 = time.perf_counter()
    res = Result("critical_nodes")
    track()
    rel = {"Service": "DEPENDS_ON", "File": "IMPORTS", "Function": "CALLS"}.get(scope)
    if not rel:
        res.data["error"] = "scope must be Service, File or Function"
        return res
    key = KEYS[scope]
    pr = _q(res, graph, f"CALL algo.pageRank('{scope}','{rel}') YIELD node, score RETURN node.{key}, score ORDER BY score DESC LIMIT $n", {"n": top}, timeout=30000)
    out = [dict(uid=uid(scope, k), pagerank=round(s, 5)) for k, s in pr.rows]
    if scope == "Service":
        bt = _q(res, graph, f"CALL algo.betweenness({{nodeLabels:['{scope}'], relationshipTypes:['{rel}']}}) YIELD node, score "
                            f"RETURN node.{key}, score", timeout=30000)
        b = dict(bt.rows)
        for o in out:
            o["betweenness"] = round(b.get(o["uid"].split(":", 1)[1], 0), 2)
    for i, o in enumerate(out):
        res.nodes[o["uid"]] = dict(label=scope, key=o["uid"].split(":", 1)[1], name=o["uid"].split(":", 1)[1])
        if scope == "Service" and i < 5:
            r = _q(res, graph, f"MATCH p=(x:Service)-[:DEPENDS_ON]->(t:Service {{name:$n}}) RETURN {PATH_PROJ} LIMIT 3", {"n": o["uid"].split(":", 1)[1]})
            o["path_ids"] = [res.add_path(*row, pid=f"critical{i + 1}_{k + 1}") for k, row in enumerate(r.rows)]
            if o["path_ids"]:
                o["path_id"] = o["path_ids"][0]
        if scope == "Service":
            o["dependents"] = _q(res, graph, "MATCH (x:Service)-[:DEPENDS_ON]->(:Service {name:$n}) RETURN count(x)", {"n": o["uid"].split(":", 1)[1]}).rows[0][0]
    res.data["critical"] = out
    res.data["note"] = f"PageRank over {rel} (edges point dependent→dependency, so high rank = many things rely on it)"
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- explain path
def explain_path(graph, a: str, b: str, max_hops: int = 6) -> Result:
    t0 = time.perf_counter()
    res = Result("explain_path")
    track()
    la, ka = resolve_target(graph, a, res)
    lb, kb = resolve_target(graph, b, res)
    if not la or not lb:
        res.data["error"] = f"could not resolve {'a' if not la else 'b'}"
        return res
    ka_, kb_ = KEYS[la], KEYS[lb]
    r = _q(res, graph, f"MATCH (a:{la} {{{ka_}:$a}}),(b:{lb} {{{kb_}:$b}}) "
                       f"WITH shortestPath((a)-[:IMPORTS|CALLS|DEPENDS_ON|DEFINES|CONTAINS*..{int(max_hops)}]->(b)) AS p "
                       f"WHERE p IS NOT NULL RETURN {PATH_PROJ}", {"a": ka, "b": kb})
    if r.rows:
        pid = res.add_path(*r.rows[0], pid="explain1")
        res.data["path_id"] = pid
        res.data["sentence"] = res.paths[0]["sentence"]
    else:
        res.data["sentence"] = "no directed path within hop limit"
    res.ms = (time.perf_counter() - t0) * 1000
    return res


# ---------------------------------------------------------------- incidents memory
def similar_incidents(graph, node_uids: list[str], top: int = 3, exclude: str | None = None) -> Result:
    t0 = time.perf_counter()
    res = Result("recall_incidents")
    track()
    files = [u.split(":", 1)[1] for u in node_uids if u.startswith("File:")]
    funcs = [u.split(":", 1)[1] for u in node_uids if u.startswith("Function:")]
    if funcs:
        r = _q(res, graph, "MATCH (f:File)-[:DEFINES]->(t:Function) WHERE t.qname IN $k RETURN DISTINCT f.path", {"k": funcs})
        files += [x[0] for x in r.rows]
    files = list(dict.fromkeys(files))
    if not files:
        res.data["similar"] = []
        return res
    r = _q(res, graph, f"MATCH p=(i:Incident)-[:AFFECTED]->(f:File) WHERE f.path IN $k AND i.id <> $ex "
                       f"RETURN i.id, i.title, i.ts, i.source, f.path, {PATH_PROJ}", {"k": files, "ex": exclude or ""})
    agg = defaultdict(lambda: dict(shared=[], paths=[]))
    for iid, title, ts, src, fp, ns, rs in r.rows:
        a = agg[iid]
        a.update(title=title, ts=ts, source=src)
        a["shared"].append(fp)
        a["paths"].append((ns, rs))
    scored = []
    for iid, a in agg.items():
        tot = _q(res, graph, "MATCH (i:Incident {id:$i})-[:AFFECTED]->(f:File) RETURN count(f)", {"i": iid}).rows[0][0]
        jac = len(a["shared"]) / max(len(set(files)) + tot - len(a["shared"]), 1)
        scored.append((jac + 0.01 * len(a["shared"]), iid, a, jac))
    out = []
    for _, iid, a, jac in sorted(scored, reverse=True)[:top]:
        c = _q(res, graph, f"MATCH p=(i:Incident {{id:$i}})-[:CAUSED_BY]->(c:Commit) RETURN c.sha, c.msg, {PATH_PROJ}", {"i": iid}).rows
        rv = _q(res, graph, f"MATCH p=(i:Incident {{id:$i}})-[:RESOLVED_BY]->(c:Commit) RETURN c.sha, c.msg, {PATH_PROJ}", {"i": iid}).rows
        pid = res.add_path(*a["paths"][0], pid=f"similar{len(out) + 1}")
        item = dict(uid=uid("Incident", iid), id=iid, title=a["title"], ts=a["ts"], source=a["source"],
                    similarity=round(jac, 3), shared_files=a["shared"][:5], path_id=pid)
        if c:
            item["caused_by"] = dict(sha=c[0][0], msg=c[0][1], path_id=res.add_path(c[0][2], c[0][3], pid=f"similar{len(out) + 1}_cause"))
        if rv:
            item["resolved_by"] = dict(sha=rv[0][0], msg=rv[0][1], path_id=res.add_path(rv[0][2], rv[0][3], pid=f"similar{len(out) + 1}_fix"))
        out.append(item)
    res.data["similar"] = out
    res.ms = (time.perf_counter() - t0) * 1000
    return res
