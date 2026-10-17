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

## D10. LLM budget: $25 total for dev + eval + demo video
- Decision: agent default model `claude-haiku-4-5-20251001` (tool loop), per-run hard caps (max 6 tool turns, max_tokens 1500, tool results truncated to ~3k chars), prompt caching on system+tools, token/cost counter in every run_finished event and a persisted spend ledger that refuses runs once $15 is spent (reserve $10 for judges/video). All deterministic analysis (L3) runs with no LLM; tests never call the API; the demo video uses recorded replays of real runs.
- Alternatives: Sonnet for every run (~5-10x cost). Why: investigation quality comes from the graph tools, not the model.

## D11. Function-level attribution via git blame at HEAD (not hunk line mapping)
- Alternatives: map historical hunk line numbers onto current function ranges (drifts after later edits; judge round 3 found a missing true cause). Why: blame is line-accurate for surviving code; edges carry source='blame'.

## D12. UI is a no-build static app (vanilla ES modules + vendored force-graph)
- Alternatives: React/Vite. Why: zero build step, works offline, one Docker layer, faster to iterate under the deadline.

## D13. Claims are verified server-side (path exists, and every sha/incident id in the text appears in the cited paths); incidents equal to a suspect's own fix commit are excluded from recall as circular.

## D14. Pivot to Reachability-to-Repair (PM verdict, 2026-10-17); v1 incident engine kept as second mode
- Gate result: 5/5. (1) OSV advisories + fixed versions; (2) vulnerable function inferred from the fix commit's changed functions (25/50 httpie advisories, 5/9 pre-commit); (3) real entry->vuln paths (httpie `core.main -> program -> collect_messages -> Session.send -> rebuild_proxies`); (4) upgrade planner (below); (5) graph changes the verdict: PyYAML 5.3.1 CVE-2020-14343 is reachable in a FullLoader app and has no path in pre-commit (SafeLoader), proven with a positive control.
- Three verdicts only: reachable / no path found within analyzed scope / unknown. "No path" is never "not exploitable".
- Static analysis limits are disclosed: dynamic dispatch not followed except class-valued parameters, functools.partial, and handlers registered on classes (call-site sensitive).

## D15. Call-site-sensitive type flow instead of a plain call graph
- Alternatives: package-level reachability (import = reachable); context-insensitive edges from the callee. Why: PyYAML's critical CVE is only reachable if the *caller* passes an unsafe loader, so edges go caller -> target, binding class-valued parameters, `functools.partial`, handlers registered on classes and handler tables. Unresolved calls stay unresolved (never guessed). A positive-control app and a synthetic-library unit test guard against the analysis going blind.

## D16. Verdict vocabulary: reachable / no path found within analyzed scope / unknown (PM requirement)
- "No path found" is never presented as "not exploitable"; the UI, claims and VEX-style draft say so explicitly. The vulnerable function is inferred from the advisory's fix commit (functions changed, or handlers a module-level change de-registered) and labelled as an inference.

## D17. Upgrade plan = deterministic, explainable ranking, not a min-cut
- The planner picks, per package, the lowest installable version >= the fix that satisfies every dependent's specifier recorded in the graph (re-evaluated after upgrades), whose own requirements hold for the other pins, and whose advisories are re-queried from OSV. Smoke checks run in a throw-away venv and are reported separately from the "fixed" claim (a plan that passes checks is not claimed to be tested by the app's full suite).
