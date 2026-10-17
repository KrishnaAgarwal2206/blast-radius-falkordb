# Decisions (ADR log)

## D1. Python + FastAPI + `falkordb` client, direct (no GraphRAG-SDK / QueryWeaver)
- Alternatives: GraphRAG-SDK, Graphiti, LangChain graph chains, QueryWeaver (AGPL, SQL-only), FalkorDB MCP server.
- Why: our value is deterministic, explainable graph traversals; frameworks hide the Cypher. We expose our own MCP tools instead.

## D2. Demo repo: open-telemetry/opentelemetry-python (pinned SHA)
- Alternatives: Netflix/dispatch (monolith, stale).
- Why: ~30 in-repo packages with real inter-package dependencies, active history, fast clone. CODEOWNERS is one catch-all team, so ownership is inferred from commits ("ownership from reality").

## D3. Drop Module node; Service = in-repo package, Package = external dependency
- Why: a Python module is a file; mixing Service/Package makes blast radius ambiguous.

## D4. Ownership is evidence: OWNS {source, score}
- Alternatives: trust CODEOWNERS only. Why: it is uninformative for the demo repo; recency-decayed commit share is real signal. Bots excluded.

## D5. Incidents derived from real fix commits; CAUSED_BY via git blame (SZZ-lite)
- Alternatives: seeded fake incidents. Why: "don't fake results". Live incidents can also be recorded by the agent.

## D6. CALLS best-effort with `confidence` label; function-level MODIFIED only for last 12 months
- Why: ast name resolution is approximate; keep claims honest and ingestion under 2 minutes.

## D7. Agent safety: tools are deterministic L3 functions; `run_cypher` guarded, uses GRAPH.RO_QUERY, forced LIMIT, timeout
- Claims must cite a path_id backed by a real query result; node IDs verified against DB.

## D8. Algorithms: native algo.pageRank / betweenness / WCC / labelPropagation / BFS (verified on server module 42201); query timeout raised per-query (default 1s kills heavy calls)
- networkx only as fallback.

## D9. Deployment: FalkorDB Cloud free tier is 100MB, no persistence, deleted after 7 days -> ship a re-seed script and replay mode; docker compose for local.
