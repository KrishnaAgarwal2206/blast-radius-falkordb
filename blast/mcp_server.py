"""MCP server exposing Blast Radius tools to any MCP client (Claude Desktop / Claude Code).

Run (stdio):  python -m blast.mcp_server
Claude Desktop config:  {"mcpServers": {"blast-radius": {"command": "python", "args": ["-m", "blast.mcp_server"]}}}
"""
import json

from mcp.server.fastmcp import FastMCP

from . import config
from .agent import tools

mcp = FastMCP("blast-radius")
G = config.DEFAULT_GRAPH


def _out(name, args, graph):
    res = tools.dispatch(graph or G, name, args)
    d = dict(res.data)
    d["paths"] = [{"path_id": p["path_id"], "sentence": p["sentence"]} for p in res.paths]
    d["cypher"] = [{"query": q.cypher, "ms": round(q.ms, 2), "rows": len(q.rows)} for q in res.queries]
    return json.dumps(d, default=str)


@mcp.tool()
def blast_radius(target: str, max_depth: int = 3, graph: str = "") -> str:
    """Everything that breaks if this service / file / function breaks (reverse dependency closure), with graph paths."""
    return _out("blast_radius", {"target": target, "max_depth": max_depth}, graph)


@mcp.tool()
def trace_stacktrace(text: str, graph: str = "") -> str:
    """Map a pasted Python stack trace to File/Function nodes; the deepest in-repo frame is the origin."""
    return _out("trace_stacktrace", {"text": text}, graph)


@mcp.tool()
def suspect_changes(nodes: list[str], window_days: int = 120, graph: str = "") -> str:
    """Rank recent commits touching the given node ids (e.g. 'File:path') by recency x churn x proximity."""
    return _out("suspect_changes", {"nodes": nodes, "window_days": window_days}, graph)


@mcp.tool()
def who_to_page(nodes: list[str], suspect_shas: list[str] | None = None, graph: str = "") -> str:
    """Inferred owners and suspect-commit authors for the given nodes, with reasons and graph paths."""
    return _out("who_to_page", {"nodes": nodes, "suspect_shas": suspect_shas}, graph)


@mcp.tool()
def recall_incidents(nodes: list[str], graph: str = "") -> str:
    """Graph memory: similar past incidents (derived from fix commits or recorded by earlier investigations)."""
    return _out("recall_incidents", {"nodes": nodes}, graph)


@mcp.tool()
def critical_nodes(scope: str = "Service", graph: str = "") -> str:
    """PageRank / betweenness single points of failure for scope Service|File|Function."""
    return _out("critical_nodes", {"scope": scope}, graph)


@mcp.tool()
def explain_path(a: str, b: str, graph: str = "") -> str:
    """Shortest dependency path between two nodes as readable hops."""
    return _out("explain_path", {"a": a, "b": b}, graph)


@mcp.tool()
def query_graph(query: str, graph: str = "") -> str:
    """Guarded read-only Cypher (no writes, LIMIT enforced, 3s timeout). Errors return the schema."""
    return _out("run_cypher", {"query": query}, graph)


@mcp.tool()
def record_incident(title: str, files: list[str], services: list[str] | None = None, cause_sha: str | None = None,
                    resolved_by_email: str | None = None, graph: str = "") -> str:
    """Persist an investigated incident into the graph so future investigations can recall it."""
    return _out("record_incident", dict(title=title, files=files, services=services or [], cause_sha=cause_sha,
                                        resolved_by_email=resolved_by_email), graph)


if __name__ == "__main__":
    mcp.run()
