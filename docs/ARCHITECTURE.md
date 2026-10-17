# Blast Radius: Proposed Architecture (v0, refined baseline)

Principle: deterministic analysis computes, the LLM routes and narrates, the graph path is the evidence. Demo target: open-telemetry/opentelemetry-python (see docs/research/problem.md).

## Refinements to the baseline (what changed and why)
1. **Drop Module as a node** (Python module == file). Keep File. Saves ingestion and viz clutter.
2. **Service = in-repo deployable package** (each dir with a pyproject; ~30 in OTel). **Package = external PyPI dependency** only. Do not mix them; DEPENDS_ON goes Service->Service and Service->Package.
3. **Ownership is evidence, not fact.** `OWNS {source:'codeowners'|'inferred', score, window_days}`; inferred = recency-decayed share of non-bot commits per Service/File (half-life ~90 days). OTel CODEOWNERS is one catch-all team, so inferred ownership is the main signal. Exclude bots (`[bot]`, renovate, dependabot) and release-bump commits.
4. **Incidents are real and derived** (no fabrication): an Incident = a fix commit/PR (message matches `fix|revert|regression`, with `(#NNNN)`). `RESOLVED_BY` -> fix Commit; `AFFECTED` -> Files/Services the fix touched; `CAUSED_BY` -> the commit that introduced the fixed lines, via `git blame` on pre-image lines (SZZ-lite, flagged `confidence`). Users can also create a live Incident from a pasted trace.
5. **MODIFIED at File level always; Function level only for last ~12 months** by mapping `git log -p -U0` hunks to function line ranges at HEAD (approximate, marked). Avoid `git log -L` (too slow).
6. **CALLS is best-effort** (`ast` name resolution through imports, same-module, `self.` methods). Edge property `confidence` in {resolved, heuristic}. Never claim more than that in the UI.
7. **SIMILAR_TO is materialized deterministically**: Jaccard over affected File/Service sets + shared stack-frame Functions + token overlap of messages. Optional embedding rerank is a bonus, never the primary signal.
8. **Frontend gets answer subgraphs, never the whole graph**; package-level collapsed view by default.
9. **Verify before relying on**: FalkorDB `algo.pageRank` is available; betweenness may not be in your server version, so fall back to networkx on an exported Service/File subgraph. Use `GRAPH.RO_QUERY` for every agent-originated query.

## Layers

### L1 Ingestion (`blast/ingest/`)
- `repo.py`: clone (blobless), pin commit SHA, list files.
- `pyast.py`: `ast` walk -> File, Class, Function (qname, lineno, end_lineno), imports, call sites.
- `packages.py`: parse pyproject -> Service nodes + DEPENDS_ON (internal vs external).
- `gitlog.py`: one `git log --since=12.months --name-status --format=...` pass + hunk pass for Function mapping; Person dedupe by email/name, bot filter.
- `codeowners.py`: parse `.github/CODEOWNERS` (glob -> file), emit OWNS(source=codeowners).
- `incidents.py`: derive Incidents from fix commits, SZZ-lite CAUSED_BY.
- Load via batched `UNWIND $rows ... MERGE` (1k rows per query); create indexes first. Target <2 min; write graph snapshot (`GRAPH.COPY`/RDB dump) for demo safety.

### L2 Graph model (`blast/graph/schema.py`)
Nodes (key property): Repo(name), Service(name, path), File(path, service, loc), Class(qname), Function(qname, file, start, end), Package(name, version), Person(email, name), Commit(sha, ts, msg, pr), Incident(id, title, ts, source).
Edges: Repo-CONTAINS->Service|File; Service-CONTAINS->File; File-DEFINES->Class|Function; Class-DEFINES->Function; File-IMPORTS->File; Function-CALLS->Function {confidence}; Service-DEPENDS_ON->Service|Package; Person-OWNS->Service|File {source,score}; Person-AUTHORED->Commit; Commit-MODIFIED->File|Function {adds,dels}; File-PART_OF->Service (redundant with CONTAINS; omit unless needed for UI, prefer one); Incident-AFFECTED->Service|File|Function; Incident-CAUSED_BY->Commit {confidence}; Incident-RESOLVED_BY->Commit; Incident-SIMILAR_TO->Incident {score, reasons}.
Indexes: File.path, Function.qname, Service.name, Commit.sha, Person.email, Incident.id.

### L3 Deterministic analysis (`blast/analysis/`, each returns `Result{summary_data, paths[], nodes[], edges[]}`)
- `blast_radius(target, depth=3)`: reverse IMPORTS/CALLS/DEPENDS_ON closure from target; group by Service; rank by distance and criticality. Returns the paths.
- `trace_stacktrace(text)`: regex frames -> map (file suffix, line) to Function via range index; origin = deepest in-repo frame; ignore stdlib/site-packages; returns ordered frame nodes + fallback to fuzzy file match.
- `suspect_changes(nodes, window_days=30)`: commits MODIFIED on origin nodes and their 1-2 hop callees/importers; score = recency decay x overlap with trace frames x hunk proximity to line x (author churn). Return top 5 with the path Commit->MODIFIED->node.
- `who_to_page(nodes|commits)`: combine suspect-commit authors (recent) and OWNS score; output primary + secondary with reason paths; flag inactive authors (no commit in 90 days).
- `critical_nodes(scope)`: PageRank (and betweenness if available) on Service/File graph; used to rank blast radius and for a "most dangerous files" panel.
- `similar_incidents(nodes)`: see L5.
- `explain_path(a, b)`: shortestPath over allowed edge types; each hop rendered as a sentence.
All Cypher is parameterized; no string interpolation of user input.

### L4 Agent + MCP (`blast/agent/`, `blast/mcp_server.py`)
- Anthropic Messages API tool-use loop (`claude-api` skill for current model IDs; use streaming). Tools = L3 functions + `run_cypher(query)`.
- `run_cypher` guard (`guard.py`): single statement; must start with MATCH/WITH/UNWIND/RETURN; reject CREATE/MERGE/DELETE/SET/REMOVE/DROP/CALL(except allowlisted algo.*)/LOAD/`;`; inject `LIMIT 200` if missing; execute via RO_QUERY with timeout; return rows + schema hint on error so the model self-corrects (max 2 retries).
- System prompt: tool-first, must cite result ids, never state a fact without a path ref (`path_id`). Final answer schema: `{impact, suspects[], page[], similar[], claims:[{text, path_ids[]}]}`.
- MCP server (python `mcp` SDK, stdio) exposing the same tools so Claude Code/Desktop can use it (track 01 plus bonus).

### L5 Incident memory (`blast/memory/`)
- Store: Incident nodes + SIMILAR_TO edges (graph is the memory). Recall = overlap of AFFECTED nodes/stack frames, then optional text rerank.
- On resolution of a live incident, write Incident + AFFECTED + CAUSED_BY + RESOLVED_BY and recompute SIMILAR_TO for it, so the next query recalls it (demo: "second similar incident is solved faster"). Also persist Person->handled->Incident via RESOLVED_BY authors for "who solved this before".

### L6 API (`blast/api/`, FastAPI)
- `POST /api/investigate {input, mode}` -> `{run_id}`; `GET /api/runs/{id}/events` SSE; `GET /api/graph/subgraph?ids=`; `GET /api/node/{id}`; `POST /api/incidents/{id}/resolve`; `GET /api/health`; `GET /api/stats`.
- Replay mode: events recorded to JSON per run, `?replay=1` re-emits them (demo insurance if the API is down).

### L7 UI (`web/`, React + Vite + react-force-graph-2d)
Left: input box (trace/service/file) + agent narration stream. Center: force graph of the answer subgraph (nodes colored by type, path edges animated/highlighted as events arrive). Right: cards for Impact, Suspects, Page, Similar incidents; clicking a claim highlights its path. Default package-level view; "expand" loads children on demand.

## Streaming event schema (SSE, one JSON per `data:` line)
```json
{"run_id":"r1","seq":12,"ts":"...","type":"<type>", ...}
```
| type | payload |
|---|---|
| `run_started` | `{input, mode}` |
| `thinking` | `{text}` (optional, short narration chunk) |
| `text_delta` | `{text}` (final-answer tokens) |
| `tool_call` | `{call_id, tool, args}` |
| `graph_query` | `{call_id, cypher, params, ms, rows}` (shown in a "show Cypher" drawer) |
| `tool_result` | `{call_id, tool, summary, node_ids[], path_ids[]}` |
| `subgraph` | `{nodes:[{id,label,type,props}], edges:[{id,source,target,type,props}]}` (merge into view) |
| `path` | `{path_id, node_ids[], edge_ids[], sentence}` (highlight; claims reference path_id) |
| `claim` | `{claim_id, text, path_ids[], kind:"impact"|"suspect"|"page"|"similar"}` |
| `error` | `{call_id?, message, recoverable}` |
| `run_finished` | `{answer:{...}, usage:{in,out}, ms}` |

## Module layout
```
blast/
  config.py  (env: FALKORDB_URL, ANTHROPIC_API_KEY, REPO_PATH, GRAPH_NAME)
  graph/{client.py, schema.py, loader.py}
  ingest/{repo.py, pyast.py, packages.py, gitlog.py, codeowners.py, incidents.py, cli.py}
  analysis/{blast_radius.py, stacktrace.py, suspects.py, who_to_page.py, critical.py, paths.py, types.py}
  memory/{similarity.py, store.py}
  agent/{loop.py, tools.py, guard.py, prompts.py, events.py}
  mcp_server.py
  api/{main.py, sse.py, replay.py}
tests/{test_guard.py, test_stacktrace.py, test_golden_scenarios.py}
web/{src/App.tsx, GraphView.tsx, Stream.tsx, Cards.tsx, api.ts}
data/{scenarios.json, replay/*.json}
```

## Build order (~24 working hours; cut lines in brackets)
| Hours | Work | Exit check |
|---|---|---|
| 0-1 | Repo skeleton, FalkorDB up (docker), client wrapper, clone OTel, pin SHA | `RETURN 1` through RO_QUERY |
| 1-3 | L1 ast + pyproject + loader; File/Class/Function/Service/IMPORTS/DEFINES/DEPENDS_ON | node counts sane; <2 min |
| 3-5 | gitlog: Person/Commit/AUTHORED/MODIFIED (file level), bot filter, inferred OWNS + CODEOWNERS | `who owns exporter-otlp-proto-grpc` matches `git shortlog` |
| 5-6 | CALLS best-effort + hunk->Function [cut: file-level only] | |
| 6-8 | L3: blast_radius, trace_stacktrace, suspect_changes, who_to_page, explain_path | golden test for 3 scenarios passes |
| 8-9 | Incident derivation (fix commits, SZZ-lite), SIMILAR_TO, similar_incidents | scenario 1 recalls 199b5718 |
| 9-10 | critical_nodes (PageRank; networkx fallback) | |
| 10-12 | L4: guard + tests, tool schemas, Anthropic loop, event emission | CLI run prints streamed events |
| 12-14 | L6 FastAPI SSE + subgraph/path events + replay recorder | curl stream works |
| 14-19 | L7 UI: stream panel, force graph, path highlight, cards, show-Cypher drawer | end-to-end scenario 1 in browser |
| 19-20 | L5 resolve flow (write incident, recall next time) | demo loop works |
| 20-21 | MCP server [cut if late] | |
| 21-22 | Record replays, snapshot graph, README, architecture diagram | cold-start in <5 min |
| 22-23 | Demo video script/run-through, fix visual polish | |
| 23-24 | Buffer, submit before deadline (Oct 18 11:59 PM IST) | |

Risks: CALLS accuracy (mitigate with confidence labels), OTel multi-name `__init__` re-exports hurting IMPORTS resolution (resolve `__init__` re-exports one hop), LLM latency (stream everything, keep tools fast), algorithm availability in FalkorDB version (networkx fallback).
