"""L4 agent: Anthropic tool-use loop over L3 tools, streaming events; plus a deterministic pipeline
(used for tests, offline mode, replay seeding, and when the spend limit is reached)."""
import hashlib
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
MAX_TURNS = 5

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
    def finalize(self, answer: dict, emit: bool = True):
        claims, dropped = [], 0
        for c in answer.get("claims", []):
            pids = [p for p in c.get("path_ids", []) if p in self.paths]
            nids = [n for n in c.get("node_ids", []) if n in self.nodes]
            if not pids:
                dropped += 1
                continue
            claims.append(dict(kind=c.get("kind", "impact"), text=c["text"], path_ids=pids, node_ids=nids,
                               claim_id=f"c{len(claims) + 1}"))
        for c in (claims if emit else []):
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
def _find_target(r: Run, text: str):
    """Free text -> the first token that resolves to a Service/File/Function (handles natural-language prompts)."""
    one = text.strip()
    if "\n" not in one and len(one) < 200 and core.resolve_target(r.graph, one)[0]:
        return one
    toks = sorted({t.strip(".,:;()'\"`") for t in re.findall(r"[\w./\-]{4,}", text)}, key=lambda t: (-bool(re.search(r"[/.\-_]", t)), -len(t)))
    for t in toks[:25]:
        if not re.search(r"[/.\-_]", t) and len(t) < 14:
            continue   # generic words (thread, exporter...) are not evidence of a target
        if core.resolve_target(r.graph, t, strict=True)[0]:
            return t
    return None


def pipeline(r: Run, text: str):
    """Same tools, fixed order, templated claims. Zero LLM cost."""
    is_trace = "Traceback" in text or 'File "' in text
    origin, frame_nodes, tr = None, [], None
    if re.search(r"^\s+at [\w.$<>]+\(.*\)|Caused by: |\.java:\d+|\.go:\d+|\.js:\d+:\d+", text, re.M) and not is_trace:
        r.send("error", message="This looks like a non-Python stack trace. Blast Radius currently ingests Python repos only; paste a Python traceback, or name a service/file/function.", recoverable=False)
        return None
    if is_trace:
        tr, _ = r.call("trace_stacktrace", {"text": text}, "t1")
        if tr and tr.data.get("origin"):
            origin = tr.data["origin_file"]
            for fr in tr.data["frames"]:
                frame_nodes += [x for x in (fr["function"], fr["file"]) if x]
        elif tr and tr.data.get("error"):
            r.send("error", message=tr.data["error"], recoverable=False)
            return None
    if origin:
        target = tr.data["origin"].split(":", 1)[1] if tr.data.get("origin", "").startswith("Function:") else origin.split(":", 1)[1]
    else:
        target = _find_target(r, text)
    if not target:
        r.send("error", message="Nothing in the graph matches that input. Name a service (e.g. opentelemetry-sdk), a file path, a function, or paste a Python traceback.", recoverable=False)
        return None
    br, _ = r.call("blast_radius", {"target": target}, "t2")
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
    focus = [x for x in ([tr.data.get("origin"), tr.data.get("origin_file")] if origin else []) if x]
    sc, _ = r.call("suspect_changes", {"nodes": seeds, "focus": focus}, "t3")
    sus = sc.data.get("suspects", []) if sc else []
    shas = [x["sha"] for x in sus]
    wp, _ = r.call("who_to_page", {"nodes": ([svc] if svc else []) + seeds[:8], "suspect_shas": shas[:3]}, "t4")
    rc, _ = r.call("recall_incidents", {"nodes": seeds}, "t5")
    cr, _ = r.call("critical_nodes", {"scope": "Service"}, "t6")
    claims = []
    imp = br.data.get("impacted", [])
    cnt = br.data["counts"]
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    tn = core.short(root) if not root.startswith("Service:") else root.split(":", 1)[1]
    if imp:
        claims.append(dict(kind="impact", text=f"If {tn} fails: {plural(cnt['Service'], 'dependent service')} and {plural(cnt['File'], 'file')} are in the blast radius (closest: {', '.join(core.short(i['uid']) for i in imp[:3])}). Evidence: {len(imp)} impacted nodes, 3 shown as paths.",
                           path_ids=[i["path_id"] for i in imp[:3]], node_ids=[i["uid"] for i in imp]))
    for i, x in enumerate(sus[:3]):
        pre = "Most likely cause" if i == 0 else "Also suspect"
        claims.append(dict(kind="cause", text=f"{pre}: {x['sha'][:8]} \"{x['msg'][:80]}\" - {x['reason']}, {x['age_days']} days before the newest commit (score {x['score']}).",
                           path_ids=[x["path_id"]], node_ids=[x["uid"]]))
    if wp:
        for x in wp.data["page"][:2]:
            claims.append(dict(kind="page", text=f"Page {x['name']}: {x['why'][:200]}{' (no commits in 90+ days, may be inactive)' if x['inactive'] else ''}.", path_ids=[x["path_id"]], node_ids=[x["uid"]]))
    if rc and rc.data["similar"]:
        sims = rc.data["similar"]
        hist = [x for x in sims if x["source"] != "live"][:1]
        mine = [x for x in sims if x["source"] == "live"][:1]
        for x in hist + mine:
            who = "Your earlier investigation" if x["source"] == "live" else "Similar past incident (from repo history)"
            claims.append(dict(kind="similar", text=f"{who} {x['id']}: \"{x['title'][:70]}\" (shares {len(x['shared_files'])} file(s), similarity {x['similarity']}).",
                               path_ids=[x["path_id"]], node_ids=[x["uid"]]))
    if cr and svc:
        for rank, o in enumerate(cr.data["critical"][:3], 1):
            if o["uid"] == svc and o.get("path_id"):
                claims.append(dict(kind="critical", text=f"{svc.split(':', 1)[1]} is the #{rank} single point of failure in this repo by PageRank over DEPENDS_ON ({o['dependents']} services depend on it directly).",
                                   path_ids=[o["path_id"]], node_ids=[svc]))
    interp = "" if target.strip() == text.strip() else f"Interpreted your input as {target if len(target) < 80 else tn}. "
    ans = dict(summary=f"{interp}{tn}: {plural(cnt['Service'], 'service')} and {plural(cnt['File'], 'file')} depend on it; {plural(len(shas), 'recent suspect commit')}; {plural(len(rc.data['similar']) if rc else 0, 'similar past incident')} recalled from graph memory.", confidence=0.6, claims=claims)
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
        id="live-" + hashlib.sha1(text.strip().encode()).hexdigest()[:10], title=_title(text), files=files[:12], services=[s.split(":", 1)[1] for s in svcs],
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
    """LLM mode: the deterministic tools run first (streamed live); the model re-ranks, verifies with at most a few
    extra tool calls, and writes the final path-cited answer. Keeps latency and cost low."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    out = pipeline(r, text)
    if out is None:
        r.send("run_finished", answer=None, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=0)
        return None
    draft, seeds, shas = out
    r.send("draft_answer", answer=r.finalize(draft, emit=False))
    brief = json.dumps({"draft_claims": [{k: c[k] for k in ("kind", "text", "path_ids")} for c in draft["claims"]],
                        "paths": {pid: p["sentence"][:160] for pid, p in r.paths.items()}}, default=str)[:7000]
    msgs = [{"role": "user", "content": f"User input:\n{text[:3000]}\n\nThe deterministic graph tools already ran. Results:\n{brief}\n\n"
             "Review them: fix any claim that looks wrong or irrelevant (e.g. a formatting commit as the cause), optionally call 1-2 tools to verify, "
             "then call final_answer with concise claims, each citing path_ids from the results above."}]
    sys_blocks = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    schemas = [dict(t) for t in tools.TOOL_SCHEMAS]
    schemas[-1]["cache_control"] = {"type": "ephemeral"}
    final_input = None
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
        r.send("error", message="agent did not produce a final answer; using the deterministic answer", recoverable=True)
        final_input = draft
    final = r.finalize(final_input)
    if remember and seeds:
        seeds = [s for s in seeds if s]
        record(r, text, seeds, shas, final)
    r.send("run_finished", answer=final, ms=round((time.perf_counter() - t0) * 1000), usage=r.tokens, cost_usd=round(r.cost, 4))
    return final
