"""Build the supply-chain graph for one app: app code + pinned third-party code, cross-package CALLS, entry points,
DEPENDS_ON with specifiers. Graph name: sc_<app>."""
import re
import time
from pathlib import Path

from ..graph.client import db, run
from ..ingest import pyast
from ..ingest.cli import batched
from . import dists
from .apps import APPS, ROUTE_DECOS
from .resolve import World

KEYS = [("Service", "name"), ("File", "path"), ("Class", "qname"), ("Function", "qname"), ("Vulnerability", "id"), ("Decision", "id"),
        ("Person", "email")]


def graph_name(app):
    return f"sc_{app}"


def ensure_checkout(spec, log=print):
    """Clone the demo app at its pinned tag if it is not already on disk (the yamlfull control ships in the repo)."""
    import subprocess
    root = Path(spec["repo"])
    if not root.exists() and spec.get("git"):
        log(f"cloning {spec['git']} @ {spec['tag']}")
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", spec["tag"], spec["git"], str(root)], check=True)


def build(app: str, log=print, fresh=True, pins_override=None, graph=None):
    spec = APPS[app]
    ensure_checkout(spec, log)
    t0 = time.perf_counter()
    g = graph or graph_name(app)
    if fresh:
        try:
            db().select_graph(g).delete()
        except Exception:
            pass
    run(g, "MERGE (:Repo {name:$n})", {"n": app}, readonly=False)
    for label, prop in KEYS:
        run(g, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})", readonly=False)
    pins = pins_override or dists.parse_pins(Path(spec["pins"]).read_text())
    files, services, rows_files = {}, [], []
    # app code
    root = Path(spec["repo"])
    for d in spec["pkg_dirs"]:
        for p in sorted((root / d).rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if dists.SKIP.search(rel):
                continue
            fi = pyast.parse_file(root, rel, app, display=f"{app}/{rel}")
            if fi:
                files[fi.path] = fi
    services.append(dict(name=app, version=spec["title"], kind="app", spec=""))
    # pinned dependencies
    metas = {}
    for name, ver in pins.items():
        m = dists.fetch(name, ver)
        metas[name] = m
        services.append(dict(name=name, version=ver, kind="dependency", spec=""))
        for rel, mod in m["files"].items():
            fi = pyast.parse_file(Path(m["root"]), rel, name, module=mod, display=f"{name}@{ver}/{rel}")
            if fi:
                files[fi.path] = fi
    log(f"parsed {len(files)} files across {len(services)} packages ({time.perf_counter() - t0:.1f}s)")
    world = World(files)
    calls = world.calls()
    disp = world.dispatch_edges()
    disp.update(world.dict_edges())
    for k, v in disp.items():
        calls.setdefault(k, v)
    log(f"resolved {len(calls)} CALLS edges ({len(disp)} via type-flow / registries) over {len(world.funcs)} functions ({time.perf_counter() - t0:.1f}s)")
    deps_by = {app: {n for n in spec["requires"] if n in pins}}
    for n, m in metas.items():
        deps_by[n] = {r for r in m["requires"] if r in pins}
    maybe = {k: v for k, v in world.maybe_calls(deps_by).items() if k not in calls}
    log(f"{len(maybe)} MAYBE_CALLS candidates from {len(world.unresolved)} unresolved dynamic call sites")
    # entry points: declared + route-like decorators in app code
    entry = set(q for q in spec["entries"] if q in world.funcs)
    for q, fn in world.funcs.items():
        if fn["file"].startswith(f"{app}/") and any(any(k in d for k in ROUTE_DECOS) for d in fn.get("decorators", [])):
            entry.add(q)
    # write
    batched(g, "UNWIND $rows AS r MERGE (s:Service {name:r.name}) SET s.version=r.version, s.kind=r.kind", services)
    def app_imports(f):
        return sorted({f"{b}:{n}" for kind, b, names in f.imports if kind == "from" and b for n in (names or []) if n != "*"})[:60]
    batched(g, "UNWIND $rows AS r MATCH (s:Service {name:r.service}) MERGE (f:File {path:r.path}) SET f.service=r.service, f.module=r.module, f.loc=r.loc, f.names=r.names, f.imports_from=r.imps "
               "MERGE (s)-[:CONTAINS]->(f)", [dict(path=f.path, service=f.service, module=f.module, loc=f.loc, names=f.toplevel[:400], imps=app_imports(f)) for f in files.values()])
    batched(g, "UNWIND $rows AS r MATCH (f:File {path:r.file}) MERGE (c:Class {qname:r.qname}) SET c.file=r.file MERGE (f)-[:DEFINES]->(c)",
            [dict(qname=q, file=fp) for f in files.values() for q, fp, _b in f.classes])
    batched(g, "UNWIND $rows AS r MATCH (f:File {path:r.file}) MERGE (n:Function {qname:r.qname}) SET n.name=r.name, n.file=r.file, n.start=r.start, "
               "n.end=r.end, n.entry=r.entry MERGE (f)-[:DEFINES]->(n)",
            [dict(qname=fn["qname"], name=fn["name"], file=fn["file"], start=fn["start"], end=fn["end"], entry=fn["qname"] in entry) for fn in world.funcs.values()])
    batched(g, "UNWIND $rows AS r MATCH (a:Class {qname:r.a}) MATCH (b:Class {qname:r.b}) MERGE (a)-[:EXTENDS]->(b)",
            [dict(a=q, b=b) for q, c in world.classes.items() for b in c["resolved"]])
    batched(g, "UNWIND $rows AS r MATCH (a:Function {qname:r.a}) MATCH (b:Function {qname:r.b}) MERGE (a)-[e:CALLS]->(b) SET e.how=r.how",
            [dict(a=a, b=b, how=h) for (a, b), h in calls.items()])
    batched(g, "UNWIND $rows AS r MATCH (a:Function {qname:r.a}) MATCH (b:Function {qname:r.b}) MERGE (a)-[e:MAYBE_CALLS]->(b) SET e.how=r.how",
            [dict(a=a, b=b, how=h) for (a, b), h in maybe.items()])
    deps = [dict(a=app, b=n, spec=spec["requires"].get(n, "")) for n in spec["requires"] if n in pins]
    for n, m in metas.items():
        deps += [dict(a=n, b=r, spec=s) for r, s in m["requires"].items() if r in pins]
    batched(g, "UNWIND $rows AS r MATCH (a:Service {name:r.a}) MATCH (b:Service {name:r.b}) MERGE (a)-[e:DEPENDS_ON]->(b) SET e.spec=r.spec", deps)
    run(g, "MATCH (r:Repo {name:$n}) MATCH (s:Service {kind:'app'}) MERGE (r)-[:CONTAINS]->(s)", {"n": app}, readonly=False)
    stats = {l: run(g, f"MATCH (n:{l}) RETURN count(n)").rows[0][0] for l in ("Service", "File", "Class", "Function")}
    stats["calls"] = run(g, "MATCH ()-[e:CALLS]->() RETURN count(e)").rows[0][0]
    stats["entries"] = sorted(entry)
    log(f"graph {g}: {stats} ({time.perf_counter() - t0:.1f}s)")
    return stats


if __name__ == "__main__":
    import sys
    build(sys.argv[1])
