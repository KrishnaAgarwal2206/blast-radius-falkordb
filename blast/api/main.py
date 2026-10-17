"""L6 API: FastAPI + SSE. Run: uvicorn blast.api.main:app"""
import asyncio
import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config
from ..agent import loop
from ..analysis import core
from ..graph import schema
from ..graph.client import list_graphs, run

app = FastAPI(title="Blast Radius", version="1.0",
              description="Graph-powered incident agent on FalkorDB. POST /api/investigate then stream /api/runs/{id}/events.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

RUNS: dict[str, dict] = {}
REPLAY_DIR = config.ROOT / "data" / "replay"
WEB_DIR = config.ROOT / "web"
MAX_INPUT = 20000


class InvestigateReq(BaseModel):
    input: str
    graph: str = config.DEFAULT_GRAPH
    llm: bool = False
    remember: bool = True


@app.get("/api/health")
def health():
    try:
        graphs = list_graphs()
        return {"ok": True, "graphs": graphs, "llm_configured": bool(config.ANTHROPIC_API_KEY),
                "spent_usd": loop.spent(), "spend_limit_usd": config.SPEND_LIMIT_USD}
    except Exception as e:
        raise HTTPException(503, f"FalkorDB unreachable: {e}")


@app.get("/api/repos")
def repos():
    from ..supply.apps import APPS
    out = []
    for g in list_graphs():
        if g == "sc_memory":
            continue
        try:
            n = run(g, "MATCH (n) RETURN count(n)").rows[0][0]
            kind = "supply" if g.startswith("sc_") else "code"
            title = APPS.get(g[3:], {}).get("title", g) if kind == "supply" else g
            out.append({"graph": g, "nodes": n, "kind": kind, "title": title})
        except Exception:
            continue
    return sorted(out, key=lambda x: (x["kind"] != "supply", x["graph"]))


@app.get("/api/supply/{app_name}")
def supply_summary(app_name: str):
    """Precomputed supply-chain snapshot: scanner view vs graph view, remediation plan and smoke-check results."""
    from ..supply import pipeline as P
    snap = P.load(app_name)
    if not snap:
        raise HTTPException(404, f"no supply snapshot for '{app_name}'. Run: python -m blast.supply.pipeline {app_name}")
    return {k: snap[k] for k in ("app", "title", "ts", "counts", "total", "scanner", "plan", "checks", "pins")}


def _require_graph(g):
    if g not in list_graphs():
        raise HTTPException(404, f"unknown graph '{g}'. Available: {list_graphs()}")


@app.get("/api/graph/{g}/stats")
def stats(g: str):
    _require_graph(g)
    return schema.stats(g)


@app.get("/api/graph/{g}/schema")
def graph_schema(g: str):
    """Meta-graph: label counts + relationship patterns with counts."""
    _require_graph(g)
    s = schema.stats(g)
    r = run(g, "MATCH (a)-[e]->(b) RETURN labels(a)[0] AS a, type(e) AS t, labels(b)[0] AS b, count(e) AS n", timeout=15000)
    return {"labels": s["nodes"], "patterns": [dict(a=x[0], type=x[1], b=x[2], n=x[3]) for x in r.rows]}


@app.get("/api/graph/{g}/critical")
def critical(g: str, scope: str = "Service"):
    _require_graph(g)
    res = core.critical_nodes(g, scope, top=15)
    return {**res.data, "queries": [dict(cypher=q.cypher, ms=q.ms) for q in res.queries]}


@app.get("/api/metrics")
def metrics():
    from ..graph.client import LATENCIES
    xs = sorted(LATENCIES)
    pct = lambda q: round(xs[min(int(len(xs) * q), len(xs) - 1)], 2) if xs else None
    return {"queries": len(xs), "p50_ms": pct(0.5), "p95_ms": pct(0.95), "max_ms": round(xs[-1], 2) if xs else None}


@app.get("/api/graph/{g}/overview")
def overview(g: str):
    """Package-level (Service) map with PageRank, betweenness and community: the default non-hairball view."""
    _require_graph(g)
    qs = []

    def q(c, **p):
        r = run(g, c, p, timeout=20000)
        qs.append(dict(cypher=r.cypher, ms=round(r.ms, 2), rows=len(r.rows)))
        return r.rows

    pr = dict(q("CALL algo.pageRank('Service','DEPENDS_ON') YIELD node, score RETURN node.name, score"))
    bt = dict(q("CALL algo.betweenness({nodeLabels:['Service'], relationshipTypes:['DEPENDS_ON']}) YIELD node, score RETURN node.name, score"))
    cm = dict(q("CALL algo.labelPropagation({nodeLabels:['Service'], relationshipTypes:['DEPENDS_ON']}) YIELD node, communityId RETURN node.name, communityId"))
    nodes = [dict(id=f"Service:{n}", label="Service", name=n, pagerank=pr.get(n, 0), betweenness=bt.get(n, 0), community=cm.get(n, 0),
                  files=f) for n, f in q("MATCH (s:Service) OPTIONAL MATCH (s)-[:CONTAINS]->(f:File) RETURN s.name, count(f)")]
    edges = [dict(id=f"Service:{a}|DEPENDS_ON|Service:{b}", source=f"Service:{a}", target=f"Service:{b}", type="DEPENDS_ON")
             for a, b in q("MATCH (a:Service)-[:DEPENDS_ON]->(b:Service) RETURN a.name, b.name")]
    if g.startswith("sc_"):
        vc = dict(q("MATCH (s:Service)-[:AFFECTED_BY]->(x:Vulnerability) RETURN s.name, count(x)"))
        ver = dict(q("MATCH (s:Service) RETURN s.name, s.version"))
        for n in nodes:
            nm = n["id"].split(":", 1)[1]
            n["vulns"], n["version"] = vc.get(nm, 0), ver.get(nm)
    return {"nodes": nodes, "edges": edges, "queries": qs}


@app.get("/api/graph/{g}/subgraph")
def subgraph(g: str, ids: str = Query(..., description="comma-separated node ids like File:path,Service:name")):
    _require_graph(g)
    by = {}
    for u in ids.split(",")[:200]:
        label, _, key = u.partition(":")
        if label in schema.KEY:
            by.setdefault(label, []).append(key)
    nodes, keys = [], {}
    for label, ks in by.items():
        r = run(g, f"MATCH (n:{label}) WHERE n.{schema.KEY[label]} IN $k RETURN n", {"k": ks})
        for (n,) in r.rows:
            u = schema.uid(label, n.properties)
            nodes.append(dict(id=u, label=label, props=n.properties))
            keys[n.id] = u
    edges = []
    if keys:
        r = run(g, "MATCH (a)-[e]->(b) WHERE id(a) IN $k AND id(b) IN $k RETURN id(a), type(e), id(b) LIMIT 1000", {"k": list(keys)})
        edges = [dict(id=f"{keys[a]}|{t}|{keys[b]}", source=keys[a], target=keys[b], type=t) for a, t, b in r.rows]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/graph/{g}/expand")
def expand(g: str, id: str, limit: int = 25):
    """Progressive expansion: neighbours of one node (both directions)."""
    _require_graph(g)
    label, _, key = id.partition(":")
    if label not in schema.KEY:
        raise HTTPException(400, "bad id")
    r = run(g, f"MATCH (a:{label} {{{schema.KEY[label]}:$k}})-[e]-(b) RETURN type(e), startNode(e)=a, labels(b)[0], "
               f"coalesce(b.path,b.qname,b.sha,b.email,b.id,b.name), coalesce(b.msg,b.title,b.name,b.qname,b.path) LIMIT $n",
            {"k": key, "n": min(limit, 60)})
    nodes, edges = {}, []
    for t, out, bl, bk, bd in r.rows:
        bu = f"{bl}:{bk}"
        nodes[bu] = dict(id=bu, label=bl, key=bk, name=bd)
        edges.append(dict(id=f"{id}|{t}|{bu}", source=id if out else bu, target=bu if out else id, type=t))
    return {"nodes": list(nodes.values()), "edges": edges, "queries": [dict(cypher=r.cypher, ms=r.ms, rows=len(r.rows))]}


@app.get("/api/incidents")
def incidents(graph: str = config.DEFAULT_GRAPH, limit: int = 50):
    _require_graph(graph)
    if graph.startswith("sc_"):   # supply mode: the memory is the shared set of verdicts (Decision nodes) made in any app
        try:
            r = run("sc_memory", "MATCH (d:Decision) RETURN d.id, d.vuln, d.app, d.verdict, d.ts, d.package ORDER BY d.ts DESC, d.vuln LIMIT $n", {"n": min(limit, 200)})
        except Exception:
            return []
        return [dict(id=a, title=f"{b} in {c}: {d.replace('_', ' ')} ({f})", ts=e, source="decision", cause=None) for a, b, c, d, e, f in r.rows]
    r = run(graph, "MATCH (i:Incident) OPTIONAL MATCH (i)-[:CAUSED_BY]->(c:Commit) "
                   "RETURN i.id, i.title, i.ts, i.source, c.sha ORDER BY i.ts DESC LIMIT $n", {"n": min(limit, 200)})
    return [dict(id=a, title=b, ts=c, source=d, cause=e) for a, b, c, d, e in r.rows]


@app.post("/api/investigate")
def investigate(req: InvestigateReq):
    if not req.input.strip():
        raise HTTPException(400, "input is empty")
    if len(req.input) > MAX_INPUT:
        raise HTTPException(413, f"input too long (max {MAX_INPUT} chars)")
    _require_graph(req.graph)
    run_id = uuid.uuid4().hex[:10]
    state = {"events": [], "done": False, "t": time.time()}
    RUNS[run_id] = state

    def work():
        try:
            loop.investigate(req.graph, req.input, state["events"].append, use_llm=req.llm, remember=req.remember)
        except Exception as e:  # last-resort guard
            state["events"].append({"type": "error", "message": str(e), "recoverable": False})
            state["events"].append({"type": "run_finished", "answer": None})
        finally:
            state["done"] = True
            try:
                REPLAY_DIR.mkdir(parents=True, exist_ok=True)
                (REPLAY_DIR / f"{run_id}.json").write_text(json.dumps(state["events"], default=str))
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()
    for k in [k for k, v in RUNS.items() if time.time() - v["t"] > 3600]:
        RUNS.pop(k, None)
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str, speed: float = 1.0):
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(404, "unknown run")

    async def gen():
        i = 0
        while True:
            while i < len(state["events"]):
                yield f"data: {json.dumps(state['events'][i], default=str)}\n\n"
                i += 1
            if state["done"] and i >= len(state["events"]):
                break
            await asyncio.sleep(0.03)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/replays")
def replays():
    return sorted(p.stem for p in (config.ROOT / "data" / "replays").glob("*.json")) if (config.ROOT / "data" / "replays").exists() else []


@app.get("/api/replays/{name}")
async def replay(name: str, pace: float = 1.0):
    """Re-emit a recorded run (demo insurance when the LLM or DB is unavailable). `pace` scales the delays."""
    p = config.ROOT / "data" / "replays" / f"{Path(name).name}.json"
    if not p.exists():
        raise HTTPException(404, "no such replay")
    evs = json.loads(p.read_text())

    async def gen():
        last = None
        for e in evs:
            if last is not None and e.get("ts") and last:
                await asyncio.sleep(min(max((e["ts"] - last) * pace, 0.0), 0.6))
            last = e.get("ts")
            yield f"data: {json.dumps(e)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")
