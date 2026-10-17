"""`python -m blast.ingest.cli <repo_path> [--graph NAME]` : build the code+history graph in FalkorDB."""
import argparse
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config
from ..graph import schema
from ..graph.client import db, run
from . import gitlog, packages, pyast

BATCH = 1000


def batched(graph, cypher, rows):
    for i in range(0, len(rows), BATCH):
        run(graph, cypher, {"rows": rows[i:i + BATCH]}, readonly=False, timeout=60000)


def resolve_imports(files: dict, modmap: dict):
    edges = set()
    for f in files.values():
        for kind, base, names in f.imports:
            targets = []
            if kind == "from":
                for n in names or []:
                    targets.append(modmap.get(f"{base}.{n}") or modmap.get(base))
            else:
                targets.append(modmap.get(base))
            for t in targets:
                if t and t != f.path:
                    edges.add((f.path, t))
    return sorted(edges)


def resolve_calls(files: dict, funcs: dict, modmap: dict):
    """Best-effort call resolution; every edge is labelled with how it was resolved."""
    out = set()
    for f in files.values():
        for caller, expr, cls in f.calls:
            parts = expr.split(".")
            cand = []
            if parts[0] == "self" and len(parts) == 2 and cls:
                cand.append((f"{f.module}.{cls}.{parts[1]}", "self-method"))
            elif len(parts) == 1:
                cand.append((f"{f.module}.{parts[0]}", "same-module"))
                if parts[0] in f.symbols:
                    base, attr = f.symbols[parts[0]]
                    if attr:
                        cand.append((f"{base}.{attr}", "import"))
                        # one-hop re-export through the target's __init__
                        tf = files.get(modmap.get(base))
                        if tf and attr in tf.symbols and tf.symbols[attr][1]:
                            b2, a2 = tf.symbols[attr]
                            cand.append((f"{b2}.{a2}", "re-export"))
            elif parts[0] in f.symbols:
                base, attr = f.symbols[parts[0]]
                if attr is None:
                    cand.append((f"{base}.{'.'.join(parts[1:])}", "import"))
                elif len(parts) == 2:
                    cand.append((f"{base}.{attr}.{parts[1]}", "import-method"))
            for q, how in cand:
                if q in funcs and q != caller:
                    out.add((caller, q, how))
                    break
    return sorted(out)


def ingest(repo: str, graph: str, months: int = 12, max_incidents: int = 120, log=print):
    t0 = time.perf_counter()
    root = Path(repo)
    # idempotent: MERGE everywhere; indexes first
    try:
        db().select_graph(graph).query("RETURN 1")
    except Exception:
        pass
    schema.create_indexes(graph)

    services = packages.discover_services(root)
    svc_names = {s["name"] for s in services}
    files, file_service = {}, {}
    for s in services:
        for p in sorted((root / s["path"] / "src").rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            fi = pyast.parse_file(root, rel, s["name"])
            if fi:
                files[rel] = fi
                file_service[rel] = s["name"]
    modmap = {f.module: f.path for f in files.values()}
    funcs = {fn["qname"]: fn for f in files.values() for fn in f.funcs}
    log(f"parsed {len(files)} files, {len(funcs)} functions in {len(services)} services ({time.perf_counter()-t0:.1f}s)")

    # ---- structure ----
    run(graph, "MERGE (:Repo {name:$n})", {"n": graph}, readonly=False)
    batched(graph, "UNWIND $rows AS r MERGE (s:Service {name:r.name}) SET s.dir=r.path", services)
    batched(graph, "UNWIND $rows AS r MATCH (s:Service {name:r.service}) MERGE (f:File {path:r.path}) "
                   "SET f.service=r.service, f.module=r.module, f.loc=r.loc MERGE (s)-[:CONTAINS]->(f)",
            [dict(path=f.path, service=f.service, module=f.module, loc=f.loc) for f in files.values()])
    batched(graph, "UNWIND $rows AS r MATCH (f:File {path:r.file}) MERGE (c:Class {qname:r.qname}) "
                   "SET c.file=r.file MERGE (f)-[:DEFINES]->(c)",
            [dict(qname=q, file=fp) for f in files.values() for q, fp in f.classes])
    batched(graph, "UNWIND $rows AS r MATCH (f:File {path:r.file}) MERGE (n:Function {qname:r.qname}) "
                   "SET n.name=r.name, n.file=r.file, n.start=r.start, n.end=r.end MERGE (f)-[:DEFINES]->(n)",
            [dict(qname=x["qname"], name=x["name"], file=x["file"], start=x["start"], end=x["end"])
             for f in files.values() for x in f.funcs])
    imp = resolve_imports(files, modmap)
    batched(graph, "UNWIND $rows AS r MATCH (a:File {path:r.a}) MATCH (b:File {path:r.b}) MERGE (a)-[:IMPORTS]->(b)",
            [dict(a=a, b=b) for a, b in imp])
    calls = resolve_calls(files, funcs, modmap)
    batched(graph, "UNWIND $rows AS r MATCH (a:Function {qname:r.a}) MATCH (b:Function {qname:r.b}) "
                   "MERGE (a)-[e:CALLS]->(b) SET e.confidence='resolved', e.how=r.how",
            [dict(a=a, b=b, how=h) for a, b, h in calls])
    deps_int = [dict(a=s["name"], b=d) for s in services for d in s["deps"] if d in svc_names]
    deps_ext = [dict(a=s["name"], b=d) for s in services for d in s["deps"] if d not in svc_names]
    batched(graph, "UNWIND $rows AS r MATCH (a:Service {name:r.a}) MATCH (b:Service {name:r.b}) MERGE (a)-[:DEPENDS_ON]->(b)", deps_int)
    batched(graph, "UNWIND $rows AS r MATCH (a:Service {name:r.a}) MERGE (p:Package {name:r.b}) MERGE (a)-[:DEPENDS_ON]->(p)", deps_ext)
    log(f"structure loaded: {len(imp)} IMPORTS, {len(calls)} CALLS, {len(deps_int)} service deps ({time.perf_counter()-t0:.1f}s)")

    # ---- history ----
    prefixes = [f"{s['path']}/src" for s in services]
    commits = gitlog.read_log(root, months, prefixes)
    commits = [c for c in commits if any(f in files for f in c["files"]) and not gitlog.NOISE.search(c["msg"])]
    log(f"git: {len(commits)} commits touching source ({time.perf_counter()-t0:.1f}s)")
    people = {}
    for c in commits:
        people.setdefault(c["email"], dict(email=c["email"], name=c["author"], bot=bool(gitlog.BOT.search(c["author"] + c["email"]))))
    batched(graph, "UNWIND $rows AS r MERGE (p:Person {email:r.email}) SET p.name=r.name, p.bot=r.bot", list(people.values()))
    crow = []
    for c in commits:
        pr = gitlog.PR.search(c["msg"])
        crow.append(dict(sha=c["sha"], ts=c["ts"], msg=c["msg"], pr=pr.group(1) if pr else None, email=c["email"]))
    batched(graph, "UNWIND $rows AS r MERGE (c:Commit {sha:r.sha}) SET c.ts=r.ts, c.msg=r.msg, c.pr=r.pr "
                   "WITH c, r MATCH (p:Person {email:r.email}) MERGE (p)-[:AUTHORED]->(c)", crow)
    fmod, fnmod = [], []
    by_file_funcs = defaultdict(list)
    for fn in funcs.values():
        by_file_funcs[fn["file"]].append(fn)
    for c in commits:
        for f, d in c["files"].items():
            if f not in files:
                continue
            fmod.append(dict(sha=c["sha"], file=f, adds=d["adds"], dels=d["dels"]))
            hit = set()
            for a, b in d["hunks"]:
                for fn in by_file_funcs[f]:
                    if fn["start"] <= b and fn["end"] >= a:
                        hit.add(fn["qname"])
            for q in list(hit)[:15]:
                fnmod.append(dict(sha=c["sha"], qname=q))
    batched(graph, "UNWIND $rows AS r MATCH (c:Commit {sha:r.sha}) MATCH (f:File {path:r.file}) "
                   "MERGE (c)-[m:MODIFIED]->(f) SET m.adds=r.adds, m.dels=r.dels", fmod)
    batched(graph, "UNWIND $rows AS r MATCH (c:Commit {sha:r.sha}) MATCH (f:Function {qname:r.qname}) "
                   "MERGE (c)-[m:MODIFIED]->(f) SET m.approx=true", fnmod)
    log(f"loaded {len(fmod)} file-level and {len(fnmod)} function-level MODIFIED edges ({time.perf_counter()-t0:.1f}s)")

    owns = gitlog.compute_ownership(commits, set(files), file_service)
    batched(graph, "UNWIND $rows AS r MATCH (p:Person {email:r.email}) MATCH (s:Service {name:r.key}) "
                   "MERGE (p)-[o:OWNS]->(s) SET o.score=r.score, o.source='inferred'", [o for o in owns if o["kind"] == "Service"])
    batched(graph, "UNWIND $rows AS r MATCH (p:Person {email:r.email}) MATCH (s:File {path:r.key}) "
                   "MERGE (p)-[o:OWNS]->(s) SET o.score=r.score, o.source='inferred'", [o for o in owns if o["kind"] == "File"])

    # ---- incidents: real fix commits, CAUSED_BY via blame ----
    fixes = [c for c in commits if gitlog.FIX.search(c["msg"]) and not people[c["email"]]["bot"]
             and 0 < sum(1 for f in c["files"] if f in files) <= 6]
    fixes = fixes[:max_incidents]

    def cause(c):
        best = None
        for f, d in c["files"].items():
            if f in files and d["old"]:
                r = gitlog.blame_cause(root, c["sha"], f, d["old"])
                if r and r["sha"] != c["sha"] and (not best or r["votes"] > best["votes"]):
                    best = r
        return c, best

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(cause, fixes))
    inc_rows, aff_rows, cause_rows, cause_commits = [], [], [], {}
    for c, b in results:
        iid = f"inc-{c['sha'][:7]}"
        fl = [f for f in c["files"] if f in files]
        inc_rows.append(dict(id=iid, title=c["msg"], ts=c["ts"], sha=c["sha"], source="fix-commit"))
        for f in fl:
            aff_rows.append(dict(id=iid, file=f, service=file_service[f]))
        if b and b.get("ts"):
            cause_commits[b["sha"]] = dict(sha=b["sha"], ts=b["ts"], msg=b.get("msg", ""), email=b.get("email", "unknown"), name=b.get("author", ""))
            cause_rows.append(dict(id=iid, cause=b["sha"], conf=round(b["votes"] / max(b["total"], 1), 2)))
    batched(graph, "UNWIND $rows AS r MERGE (i:Incident {id:r.id}) SET i.title=r.title, i.ts=r.ts, i.source=r.source "
                   "WITH i, r MATCH (c:Commit {sha:r.sha}) MERGE (i)-[:RESOLVED_BY]->(c)", inc_rows)
    batched(graph, "UNWIND $rows AS r MATCH (i:Incident {id:r.id}) MATCH (f:File {path:r.file}) MERGE (i)-[:AFFECTED]->(f) "
                   "WITH i, r MATCH (s:Service {name:r.service}) MERGE (i)-[:AFFECTED]->(s)", aff_rows)
    cc = list(cause_commits.values())
    batched(graph, "UNWIND $rows AS r MERGE (p:Person {email:r.email}) ON CREATE SET p.name=r.name, p.bot=false "
                   "MERGE (c:Commit {sha:r.sha}) ON CREATE SET c.ts=r.ts, c.msg=r.msg "
                   "MERGE (p)-[:AUTHORED]->(c)", cc)
    batched(graph, "UNWIND $rows AS r MATCH (i:Incident {id:r.id}) MATCH (c:Commit {sha:r.cause}) "
                   "MERGE (i)-[e:CAUSED_BY]->(c) SET e.confidence=r.conf", cause_rows)
    # SIMILAR_TO: Jaccard on affected files
    aff = defaultdict(set)
    for r in aff_rows:
        aff[r["id"]].add(r["file"])
    sim = []
    ids = list(aff)
    for i, a in enumerate(ids):
        scored = []
        for b in ids[i + 1:]:
            inter = aff[a] & aff[b]
            if inter:
                j = len(inter) / len(aff[a] | aff[b])
                if j >= 0.2:
                    scored.append((j, b, sorted(inter)[:3]))
        for j, b, sh in sorted(scored, reverse=True)[:3]:
            sim.append(dict(a=a, b=b, score=round(j, 2), shared=sh))
    batched(graph, "UNWIND $rows AS r MATCH (a:Incident {id:r.a}) MATCH (b:Incident {id:r.b}) "
                   "MERGE (a)-[s:SIMILAR_TO]->(b) SET s.score=r.score, s.shared=r.shared", sim)
    log(f"incidents: {len(inc_rows)} (with {len(cause_rows)} CAUSED_BY), {len(sim)} SIMILAR_TO ({time.perf_counter()-t0:.1f}s)")
    stats = schema.stats(graph)
    log(f"DONE in {time.perf_counter()-t0:.1f}s  nodes={stats['nodes']}  edges={stats['edges']}")
    return stats


def clone_if_url(repo: str, log=print) -> str:
    """`blast ingest <url|path>`: clone URLs into data/repos/<name> (full history, needed for blame)."""
    if not re.match(r"^(https?://|git@)", repo):
        return repo
    import subprocess
    dest = config.ROOT / "data" / "repos" / re.sub(r"\.git$", "", repo.rstrip("/").split("/")[-1])
    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "pull", "-q", "--ff-only"], check=False)
    else:
        log(f"cloning {repo} ...")
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", repo, str(dest)], check=True)
    return str(dest)


def main():
    ap = argparse.ArgumentParser(description="Ingest a Python monorepo into a FalkorDB graph (one graph per repo)")
    ap.add_argument("repo", nargs="?", default=config.REPO_PATH, help="local path or git URL")
    ap.add_argument("--graph", default=config.DEFAULT_GRAPH)
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args()
    ingest(clone_if_url(a.repo), a.graph, a.months)


if __name__ == "__main__":
    main()
