"""Agent tools = L3 functions + guarded run_cypher. Also used by the MCP server."""
import json

from ..analysis import core
from ..graph.client import run
from ..memory import store
from . import guard


def _cypher_tool(graph, query):
    res = core.Result("run_cypher")
    try:
        safe = guard.check(query)
        r = run(graph, safe, timeout=3000)
        res.queries.append(r)
        res.data = {"columns": r.header, "rows": [[str(c)[:120] for c in row] for row in r.rows[:40]], "row_count": len(r.rows)}
    except guard.GuardError as e:
        res.data = {"error": f"rejected by guard: {e}", "schema": guard.SCHEMA_HINT}
    except Exception as e:  # server-side syntax errors etc.: let the model self-correct
        res.data = {"error": str(e)[:300], "schema": guard.SCHEMA_HINT}
    return res


def dispatch(graph, name, args):
    if name == "trace_stacktrace":
        return core.trace_stacktrace(graph, args.get("text", ""))
    if name == "blast_radius":
        return core.blast_radius(graph, args.get("target", ""), int(args.get("max_depth", 3)))
    if name == "suspect_changes":
        return core.suspect_changes(graph, args.get("nodes", []), int(args.get("window_days", 120)), focus=args.get("focus"))
    if name == "who_to_page":
        return core.who_to_page(graph, args.get("nodes", []), args.get("suspect_shas"))
    if name == "recall_incidents":
        return core.similar_incidents(graph, args.get("nodes", []), exclude=args.get("exclude"))
    if name == "critical_nodes":
        return core.critical_nodes(graph, args.get("scope", "Service"))
    if name == "explain_path":
        return core.explain_path(graph, args.get("a", ""), args.get("b", ""))
    if name == "dependent_owners":
        return core.dependent_owners(graph, args.get("services", []))
    if name.startswith("sc_"):
        from ..supply import agent as sa
        return {"sc_findings": sa.t_findings, "sc_plan": sa.t_plan, "sc_checks": sa.t_checks, "sc_recall": sa.t_recall, "sc_preflight": sa.t_preflight}[name](graph, args)
    if name == "run_cypher":
        return _cypher_tool(graph, args.get("query", ""))
    if name == "record_incident":
        return store.record_incident(graph, args)
    raise ValueError(f"unknown tool {name}")


NODES = {"type": "array", "items": {"type": "string"},
         "description": "Node ids as returned by other tools, e.g. 'File:path' or 'Function:qname' or 'Service:name'"}

TOOL_SCHEMAS = [
    {"name": "trace_stacktrace", "description": "Parse a Python stack trace and map frames to File/Function nodes. origin = deepest in-repo frame.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "blast_radius", "description": "Reverse-dependency closure: everything that breaks if target (service name, file path/suffix, or function) breaks. Returns impacted nodes with depth and path_id.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "max_depth": {"type": "integer"}}, "required": ["target"]}},
    {"name": "suspect_changes", "description": "Rank recent commits touching the given nodes (and their imports) by recency x churn x proximity.",
     "input_schema": {"type": "object", "properties": {"nodes": NODES, "window_days": {"type": "integer"}}, "required": ["nodes"]}},
    {"name": "who_to_page", "description": "Who to page: inferred owners of the nodes' services/files plus authors of suspect commits.",
     "input_schema": {"type": "object", "properties": {"nodes": NODES, "suspect_shas": {"type": "array", "items": {"type": "string"}}}, "required": ["nodes"]}},
    {"name": "recall_incidents", "description": "Graph memory: past incidents (incl. ones recorded by earlier investigations) affecting the same files, with cause and fix.",
     "input_schema": {"type": "object", "properties": {"nodes": NODES}, "required": ["nodes"]}},
    {"name": "critical_nodes", "description": "PageRank/betweenness single points of failure for scope Service|File|Function.",
     "input_schema": {"type": "object", "properties": {"scope": {"type": "string"}}}},
    {"name": "explain_path", "description": "Shortest dependency path between two nodes, as human-readable hops.",
     "input_schema": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}},
    {"name": "run_cypher", "description": "Escape hatch: read-only Cypher (guarded: no writes, LIMIT enforced, 3s timeout). Prefer other tools. Errors return the schema.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "final_answer", "description": "Finish. Every claim MUST cite path_ids returned by tools; uncited claims are discarded.",
     "input_schema": {"type": "object", "properties": {
         "summary": {"type": "string", "description": "2-4 sentence incident summary"},
         "confidence": {"type": "number"},
         "claims": {"type": "array", "items": {"type": "object", "properties": {
             "kind": {"type": "string", "enum": ["impact", "cause", "page", "similar", "critical"]},
             "text": {"type": "string"},
             "path_ids": {"type": "array", "items": {"type": "string"}},
             "node_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["kind", "text", "path_ids"]}},
         "verification": {"type": "array", "description": "Your independent check of each diagnosis step (s1..) and recommended action (a1..) from the brief: is it supported by the cited path sentences?",
                          "items": {"type": "object", "properties": {"ref": {"type": "string"}, "verdict": {"type": "string", "enum": ["supported", "weak", "unsupported"]},
                                                                      "reason": {"type": "string"}}, "required": ["ref", "verdict", "reason"]}}},
         "required": ["summary", "claims", "confidence", "verification"]}},
]


def compact(res: core.Result, limit=3500) -> str:
    d = dict(res.data)
    if "impacted" in d:
        d["impacted"] = [{k: v for k, v in i.items()} for i in d["impacted"][:25]]
    d["paths"] = [{"path_id": p["path_id"], "sentence": p["sentence"][:200]} for p in res.paths[:25]]
    s = json.dumps(d, default=str)
    return s if len(s) <= limit else s[:limit] + '..."truncated"'
