"""L4 agent: Anthropic tool-use loop over L3 tools, streaming events; plus a deterministic pipeline
(used for tests, offline mode, replay seeding, and when the spend limit is reached)."""
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .. import config
from ..analysis import core
from ..memory import store
from . import tools

# $ per million tokens (Haiku 4.5)
PRICE = {"in": 1.0, "out": 5.0, "cache_read": 0.10, "cache_write": 1.25}
MAX_TURNS = 9

SYSTEM = """You are Blast Radius, an incident-investigation agent. You reason ONLY through a FalkorDB graph of a codebase \
(Services = in-repo packages, Files, Functions, Commits, Persons, past Incidents). Never state a fact you did not get from a tool.

Workflow (skip steps that don't apply):
1. If the user pasted a stack trace, call trace_stacktrace first; its `origin` is the failing node.
   Otherwise call blast_radius on the named service/file/function.
2. Call blast_radius on the origin (file or function) if you haven't, then suspect_changes on [origin + files of the failing service/impacted nodes], then who_to_page with the top suspect shas, then recall_incidents on the origin/affected files.
3. Optionally critical_nodes or explain_path. Use run_cypher only if the other tools can't answer.
4. Finish with final_answer. Each claim must cite path_ids that tools returned (e.g. impact1, suspect1, page1, similar1). Claims without valid path_ids are discarded. Be concise and concrete; mention commit sha prefixes, names, depths. State uncertainty honestly (ownership is inferred from commits; CALLS edges are best-effort).
Tool results are compact JSON. Node ids look like 'File:path', 'Function:qname', 'Service:name', 'Commit:sha'."""


@dataclass
class Run:
    graph: str
    emit: Callable
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    seq: int = 0
    nodes: dict = field(default_factory=dict)
    edges: set = field(default_factory=set)
    paths: dict = field(default_factory=dict)
    cost: float = 0.0
    tokens: dict = field(default_factory=lambda: {"in": 0, "out": 0})
    results: dict = field(default_factory=dict)   # tool name -> last Result (for the deterministic answer)

    def send(self, type_, **payload):
        self.seq += 1
        self.emit({"run_id": self.run_id, "seq": self.seq, "ts": time.time(), "type": type_, **payload})

    # --- run one tool, stream everything it did
    def call(self, name, args, call_id):
        self.send("tool_call", call_id=call_id, tool=name, args=args)
        t0 = time.perf_counter()
        try:
            res = tools.dispatch(self.graph, name, args)
        except Exception as e:
            self.send("error", call_id=call_id, message=f"{name} failed: {e}", recoverable=True)
            return None, json.dumps({"error": str(e)[:200]})
        # path-id uniqueness across calls
        data_s = None
        for p in res.paths:
            if p["path_id"] in self.paths:
                new = f"{p['path_id']}_{call_id}"
                data_s = (data_s or json.dumps(res.data, default=str)).replace(f'"{p["path_id"]}"', f'"{new}"')
                p["path_id"] = new
        if data_s:
            res.data = json.loads(data_s)
        for q in res.queries:
            self.send("graph_query", call_id=call_id, tool=name, cypher=q.cypher, params=_short(q.params), ms=round(q.ms, 2),
                      rtt_ms=round(q.rtt_ms, 1), rows=len(q.rows))
        new_nodes = {u: n for u, n in res.nodes.items() if u not in self.nodes}
        self.nodes.update(res.nodes)
        new_edges = [e for e in res.edges if e not in self.edges]
        self.edges.update(new_edges)
        if new_nodes or new_edges:
            self.send("subgraph", call_id=call_id,
                      nodes=[dict(id=u, **n) for u, n in new_nodes.items()],
                      edges=[dict(id=f"{a}|{t}|{b}", source=a, target=b, type=t) for a, t, b in new_edges])
        for p in res.paths:
            self.paths[p["path_id"]] = p
            self.send("path", call_id=call_id, **p)
        self.results[name] = res
        self.send("tool_result", call_id=call_id, tool=name, ms=round((time.perf_counter() - t0) * 1000, 1),
                  summary=_summary(name, res), node_ids=list(res.nodes)[:50], path_ids=[p["path_id"] for p in res.paths])
        return res, tools.compact(res)

    # --- verify a model-produced answer against what the graph actually returned
    def finalize(self, answer: dict):
        claims, dropped = [], 0
        for c in answer.get("claims", []):
            pids = [p for p in c.get("path_ids", []) if p in self.paths]
            nids = [n for n in c.get("node_ids", []) if n in self.nodes]
            if not pids:
                dropped += 1
                continue
            claims.append(dict(kind=c.get("kind", "impact"), text=c["text"], path_ids=pids, node_ids=nids,
                               claim_id=f"c{len(claims) + 1}"))
        for c in claims:
            self.send("claim", **c)
        by = lambda k: [c for c in claims if c["kind"] == k]
        out = dict(summary=answer.get("summary", ""), confidence=answer.get("confidence"),
                   impacted=by("impact"), likely_cause=(by("cause") or [None])[0], page=by("page"),
                   similar_incidents=by("similar"), critical=by("critical"), claims=claims,
                   evidence_paths=[self.paths[p] for p in dict.fromkeys(p for c in claims for p in c["path_ids"])],
                   dropped_unverified_claims=dropped)
        return out


def _short(params):
    return {k: (v if not isinstance(v, list) or len(v) < 6 else v[:5] + [f"...+{len(v) - 5}"]) for k, v in params.items()}


def _summary(name, res):
    d = res.data
    if "error" in d:
        return d["error"]
    if name == "blast_radius":
        return f"{len(d.get('impacted', []))} impacted: {d.get('counts')}"
    if name == "trace_stacktrace":
        return f"{d.get('in_repo_frames')}/{d.get('frames_parsed')} frames mapped; origin {core.short(d['origin']) if d.get('origin') else None}"
    if name == "suspect_changes":
        return f"{len(d.get('suspects', []))} suspect commits"
    if name == "who_to_page":
        return ", ".join(p["name"] for p in d.get("page", [])) or "nobody found"
    if name == "recall_incidents":
        return f"{len(d.get('similar', []))} similar past incidents"
    return json.dumps(d, default=str)[:160]


def _cost(u):
    return (u.input_tokens * PRICE["in"] + u.output_tokens * PRICE["out"]
            + (getattr(u, "cache_read_input_tokens", 0) or 0) * PRICE["cache_read"]
            + (getattr(u, "cache_creation_input_tokens", 0) or 0) * PRICE["cache_write"]) / 1e6


# ---------------------------------------------------------------- spend ledger
def spent() -> float:
    try:
        return json.loads(config.LEDGER_PATH.read_text())["usd"]
    except Exception:
        return 0.0


def add_spend(usd):
    config.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.LEDGER_PATH.write_text(json.dumps({"usd": round(spent() + usd, 5)}))


# ---------------------------------------------------------------- deterministic pipeline
def pipeline(r: Run, text: str):
    """Same tools, fixed order, templated claims. Zero LLM cost."""
    is_trace = "Traceback" in text or 'File "' in text
    origin, frame_nodes, tr = None, [], None
    if is_trace:
        tr, _ = r.call("trace_stacktrace", {"text": text}, "t1")
        if tr and tr.data.get("origin"):
            origin = tr.data["origin_file"]
            for fr in tr.data["frames"]:
                frame_nodes += [x for x in (fr["function"], fr["file"]) if x]
    target = origin.split(":", 1)[1] if origin else text.strip().splitlines()[0][:200]
    br, _ = r.call("blast_radius", {"target": (tr.data["origin"].split(":", 1)[1] if origin and tr.data.get("origin", "").startswith("Function:") else target)}, "t2")
    if not br or "error" in br.data:
        r.send("error", message=(br.data.get("error") if br else "blast_radius failed"), recoverable=False)
        return None
    root = br.data["target"]
    svc = br.data.get("service") or (root if root.startswith("Service:") else None)
    if root.startswith("Service:"):   # a whole service: seeds are its files
        q = core.run(r.graph, "MATCH (:Service {name:$n})-[:CONTAINS]->(f:File) RETURN f.path", {"n": root.split(':', 1)[1]})
        seeds = ["File:" + x[0] for x in q.rows]
    elif frame_nodes:                 # a stack trace: seeds are exactly the frames the trace passed through
        seeds = list(dict.fromkeys(frame_nodes))
    else:
        seeds = [root]
    sc, _ = r.call("suspect_changes", {"nodes": seeds}, "t3")
    shas = [s["sha"] for s in (sc.data.get("suspects", []) if sc else [])]
    wp, _ = r.call("who_to_page", {"nodes": ([svc] if svc else []) + seeds[:8], "suspect_shas": shas[:3]}, "t4")
    rc, _ = r.call("recall_incidents", {"nodes": seeds}, "t5")
    r.call("critical_nodes", {"scope": "Service"}, "t6")
    claims = []
    imp = br.data.get("impacted", [])
    if imp:
        c = br.data["counts"]
        claims.append(dict(kind="impact", text=f"{root.split(':',1)[1].split('/')[-1]} failing affects {c['Service']} dependent services and {c['File']} files (closest: {', '.join(core.short(i['uid']) for i in imp[:3])}).",
                           path_ids=[i["path_id"] for i in imp[:3]], node_ids=[i["uid"] for i in imp[:3]]))
    if sc and sc.data["suspects"]:
        s = sc.data["suspects"][0]
        claims.append(dict(kind="cause", text=f"Most likely cause: {s['sha'][:8]} \"{s['msg'][:80]}\" ({s['age_days']}d before head, touches the {s['via']}).",
                           path_ids=[s["path_id"]], node_ids=[s["uid"]]))
    if wp:
        for p in wp.data["page"][:2]:
            claims.append(dict(kind="page", text=f"Page {p['name']}: {p['why'][:120]}.", path_ids=[p["path_id"]], node_ids=[p["uid"]]))
    if rc and rc.data["similar"]:
        s = rc.data["similar"][0]
        claims.append(dict(kind="similar", text=f"Similar past incident {s['id']}: \"{s['title'][:70]}\" (shared files {len(s['shared_files'])}, similarity {s['similarity']}).",
                           path_ids=[s["path_id"]], node_ids=[s["uid"]]))
    tn = core.short(root) if not root.startswith("Service:") else root.split(":", 1)[1]
    ans = dict(summary=f"{tn} → {br.data['counts']['Service']} services and {br.data['counts']['File']} files depend on it; {len(shas)} recent suspect commit(s) touch it; {len(rc.data['similar']) if rc else 0} similar past incident(s) recalled from graph memory.", confidence=0.6, claims=claims)
    return ans, seeds, shas


def _title(text: str) -> str:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if "Traceback" in text or 'File "' in text:
        return (lines[-1] if lines else "stack trace")[:120]
    return (lines[0] if lines else "incident")[:120]


def record(r: Run, text: str, seeds, shas, answer):
    """L5: persist this investigation as an Incident so later runs can recall it."""
    files = [s.split(":", 1)[1] for s in seeds if s.startswith("File:")]
    sim = [c["node_ids"][0].split(":", 1)[1] for c in answer["similar_incidents"] if c["node_ids"]]
    svcs = list(dict.fromkeys(f for f in (r.results.get("blast_radius").data.get("service"),) if f))
    res, _ = r.call("record_incident", dict(
        title=_title(text), files=files[:12], services=[s.split(":", 1)[1] for s in svcs],
        cause_sha=shas[0] if shas else None, similar_ids=sim), "rec")
    return res


def investigate(graph, text, emit, use_llm=True, remember=True):
    r = Run(graph, emit)
    t0 = time.perf_counter()
    r.send("run_started", input=text[:2000], mode="llm" if use_llm else "deterministic", graph=graph)
    try:
        if use_llm and config.ANTHROPIC_API_KEY and spent() < config.SPEND_LIMIT_USD:
            return _agent(r, text, t0, remember)
        if use_llm:
            r.send("error", message="LLM unavailable (no key or spend limit reached); using deterministic pipeline", recoverable=True)
        out = pipeline(r, text)
        if out is None:
            r.send("run_finished", answer=None, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=0)
            return None
        ans, seeds, shas = out
        final = r.finalize(ans)
        if remember:
            record(r, text, seeds, shas, final)
        r.send("run_finished", answer=final, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=0)
        return final
    except Exception as e:
        r.send("error", message=f"investigation crashed: {e}", recoverable=False)
        r.send("run_finished", answer=None, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=round(r.cost, 4))
        return None


def _agent(r: Run, text: str, t0, remember):
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msgs = [{"role": "user", "content": text[:6000]}]
    sys_blocks = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    schemas = [dict(t) for t in tools.TOOL_SCHEMAS]
    schemas[-1]["cache_control"] = {"type": "ephemeral"}
    final_input = None
    seeds, shas = [], []
    for turn in range(MAX_TURNS):
        if spent() + r.cost >= config.SPEND_LIMIT_USD:
            r.send("error", message="spend limit reached", recoverable=False)
            break
        with client.messages.stream(model=config.AGENT_MODEL, max_tokens=1500, system=sys_blocks, tools=schemas, messages=msgs) as st:
            for ev in st:
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    r.send("thinking", text=ev.delta.text)
            msg = st.get_final_message()
        r.cost += _cost(msg.usage)
        r.tokens["in"] += msg.usage.input_tokens
        r.tokens["out"] += msg.usage.output_tokens
        if os.getenv("BLAST_DEBUG"):
            print("TURN", turn, msg.stop_reason, [b.type + ':' + getattr(b, 'name', '') for b in msg.content], msg.usage.input_tokens, msg.usage.output_tokens, file=sys.stderr)
        msgs.append({"role": "assistant", "content": msg.content})
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            break
        results = []
        for b in calls:
            if b.name == "final_answer":
                final_input = b.input
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "ok"})
                continue
            res, content = r.call(b.name, b.input, f"{b.name[:3]}{turn}{len(results)}")
            if res and b.name == "suspect_changes":
                shas = [s["sha"] for s in res.data.get("suspects", [])]
            if res and b.name in ("blast_radius", "trace_stacktrace") and "error" not in res.data:
                seeds += [res.data.get("origin_file") or res.data.get("target")]
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": content})
        msgs.append({"role": "user", "content": results})
        if final_input:
            break
    add_spend(r.cost)
    if not final_input:
        r.send("error", message="agent did not produce a final answer; falling back to deterministic pipeline", recoverable=True)
        out = pipeline(r, text)
        if out is None:
            r.send("run_finished", answer=None, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=round(r.cost, 4))
            return None
        final_input, seeds, shas = out
    final = r.finalize(final_input)
    if remember and seeds:
        seeds = [s for s in seeds if s]
        record(r, text, seeds, shas, final)
    r.send("run_finished", answer=final, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=round(r.cost, 4))
    return final
