# Blast Radius - independent judge, round 1

Method: ran the live product (UI via Playwright screenshots, API, deterministic mode), 2 LLM runs, pytest (31 passed), fresh ingest into `judge_tmp` (deleted afterwards), read blast/ and web/ source.
Hackathon: Graph Hacks (WeMakeDevs x FalkorDB), tracks 01 Agents That Act on Connected Data / 02 Agent Memory / 03 Company Brain. Rules: FalkorDB must do essential work; submission needs source, README with setup, Cypher queries, demo video, live deploy or local setup; AI use disclosed; participant must understand code.

## Scores

| # | Criterion | Target | Score | One-line evidence |
|---|---|---|---|---|
| 1 | FalkorDB central | >=9 | 8 | Variable-length IMPORTS/CALLS/DEPENDS_ON traversals, shortestPath, pageRank/betweenness/labelPropagation, RO_QUERY, MODIFIED/CAUSED_BY attribution. But the algorithms only feed a side lens; `critical` is `[]` in every answer and nothing in the verdict uses PageRank/betweenness. |
| 2 | Correctness (5 scenarios) | 5/5 | 3 full + 2 partial | Impact right 5/5; root-cause ranking right 3/5 (see below) |
| 3 | Explainability | >=9 | 7 | Every claim has path_ids and clicking one highlights the path. But the check only tests that the id exists, not that it supports the text; "14 services and 25 files" is backed by 3 paths. |
| 4 | Demo wow | >=8 | 7 | Hero + live feed + Cypher/ms panel are clear. Final graph is a label-overlapping hairball; Answer text overflows the right panel; lens switch changes nothing visible on the investigation view; schema modal is cramped and clipped. |
| 5 | Track fit | >=8 | 7 | 01 credible, but default mode is a fixed pipeline (no agent decisions); LLM mode is flaky. 03 (owners inferred from commits) is thin. 02 memory is real (Incident write-back) but self-recall inflates it. |
| 6 | Robustness | >=8 | 7 | Empty 400, >20k 413, bad graph 404, injection and Cypher-injection strings are inert, DB intact. But error text is poor (bugs 3,4), and LLM mode can end with no answer. |
| 7 | Performance | >=8 | 9 | Ingest 3.2 s (judge_tmp, 2089 fn / 3579 MODIFIED edges). Deterministic investigation 94 ms server side, 48 queries, 27 ms DB, p95 1.6 ms, shown in header. LLM runs 31-38 s (misses the 20 s target). |
| 8 | Setup | works 1st try | 7 | Compose/Dockerfile/README consistent. Risks: unpinned clone makes README SHAs non-reproducible; heavy requirements (playwright in runtime image); CDN dependencies. |
| 9 | Code quality | >=8 | 7 | Clean layers, 31 tests, read-only guard for run_cypher, no secrets in tree or history. Dings: tracked files that .gitignore lists, stale test count in README, 4 commits total. |
| 10 | Originality | >=8 | 7 | Blame-derived incident graph + evidence path per claim + live Cypher panel is a good combo, but code-graph + blast radius is a well-trodden FalkorDB demo shape and the default mode is templated. |

## Scenario results (checked against data/repos/otel with git/grep)

1. README 1 (data/scenario3_trace.txt): origin SynchronousMeasurementConsumer.collect, 14 services / 25 files, top suspect 66a7c08f. Matches README. PASS. Caveat: 66a7c08f is itself a fix commit ("Fix metrics collection timeout...") named "most likely cause", and the recalled "similar incident" (live-1792242162) is an earlier run of the same trace (similarity 1.0).
2. README 2 `opentelemetry-exporter-otlp-proto-grpc`: only dependent = opentelemetry-exporter-otlp (verified in pyproject.toml). Suspects f36c1288 / 8acde049 verified as the two newest commits on the exporter. PASS ("1 services and 0 files" grammar).
3. README 3 `.../metrics/_internal/view.py`: importers by grep = view/__init__.py, metric_reader_storage.py, _view_instrument_match.py, all returned; top suspect 8c870181 is the newest commit on the file. PASS.
4. NEW A: authored trace BatchProcessor worker -> _export (sdk/_shared_internal/__init__.py:187) -> trace_exporter export (:138) -> grpc exporter.py:450 `_export`. Origin correctly OTLPExporterMixin._export. Cause returned: 3701d6b1 "Keep spans mutable during on_ending..." which only edits sdk/trace/__init__.py (a 2-hop import "dependency") while f36c1288 and 8acde049 directly modify exporter.py. PARTIAL.
5. NEW B: `opentelemetry-api/src/opentelemetry/context/__init__.py`: 21 services / 131 files (plausible; 17 pyproject files name opentelemetry-api, rest transitive). Top suspect 0110bb1d "Update line length to 120" (a formatting commit, 70 days old). Also `BatchProcessor.worker` -> top suspect eee0da65, 56 days old. PARTIAL.

## Bugs (with repro)

1. LLM mode, natural language: `POST /api/investigate {"input":"The OTLP gRPC exporter is failing at startup in prod. What breaks, what changed recently, who do I page?","llm":true}` -> 28 tool calls (many guessed run_cypher queries against a non-existent `TOUCHED` rel), 36 s, no final_answer, deterministic fallback errors "no Service/File/Function matches '<whole sentence>'", run_finished.answer = null. $0.06 for nothing.
2. LLM mode with service name: 31 s; answer drops the impact claim entirely (dependent opentelemetry-exporter-otlp not mentioned); summary prose partly un-pathed.
3. Wrong error messages: malformed trace, third-party-only trace (`File "/usr/lib/python3/site-packages/requests/api.py", line 59, in get`) and a Java trace all return "no Service/File/Function matches 'Traceback (most recent call last):'" instead of the trace tool's own "frames parsed but none map to files in this graph". UI shows a generic "Nothing in the graph matched that input".
4. Natural language in default mode is looked up as one string (resolve_target) and fails; no keyword extraction.
5. UI: Answer panel text overflows (long qnames not wrapped, clipped). Graph label collisions. Lens buttons (PageRank/Blast depth/Community) do nothing visible on an investigation subgraph. Schema modal shapes overlap/clipped. Memory timeline says 40 incidents while stats show 62-63 Incident nodes.
6. Memory self-recall: every UI run (remember=true default) writes a `live-*` Incident; re-running a trace yields "similar incident, similarity 1.0" to itself, and live incidents get a +0.1 rank bonus.
7. Claim text: "1 services", "owns ... (inferred sco." cut mid-word at 120 chars.
8. README says 29 tests (actual 31); `data/spend_ledger.json` and `data/replay/*.json` are tracked although .gitignore lists them; README SHAs depend on an unpinned `git clone` of HEAD.
9. UI depends on CDNs (unpkg force-graph, Google Fonts): offline demo breaks.

Secrets: grep of `git log -p` / tracked files for sk-ant and api_key= found nothing; .env ignored. README does not link a demo video or a standalone Cypher file, which the rules list as submission items (docs/DEMO_SCRIPT.md exists).

## Prioritized fix list

1. Fix cause ranking: weight direct edits (same file/function frames) far above `dependency` hops; never let a hop-2 commit outrank direct commits; down-rank formatting/lint/version-bump commits ("line length", "ruff", "Update version", "chore"); show top-3 with reasons. Fixes scenarios 4 and 5.
2. Make LLM mode reliable: cap ~6 turns, forbid guessing rel types, seed it with the deterministic result and let it only re-rank/narrate, ensure the fallback gets a resolved target. Target <20 s.
3. Bridge natural language in default mode: extract candidate tokens and fuzzy-match services/files/functions; surface trace_stacktrace's real error text on parse failures.
4. Make "every claim has a path" real: verify cited path endpoints contain the nodes the claim names, give counts a "show all 39" evidence list, and use PageRank/betweenness in a verdict (e.g. flag a top-3 single point of failure).
5. UI polish for the 90-second demo: wrap long qnames; layered layout with labels only for origin/suspects/hover; make lenses recolor the investigation subgraph; fix schema modal; add a one-line "why a graph" caption.
6. Memory hygiene: dedupe self-runs by input hash, drop the live-incident rank bonus, make Memory count match stats, label "your earlier investigation".
7. Reproducibility/setup: pin the demo repo commit so README SHAs/numbers reproduce; untrack spend_ledger.json and data/replay; split runtime vs dev requirements; self-host force-graph and fonts; link demo video and add a queries.cypher file.
8. Nits and tests: pluralisation, no mid-word truncation, update test count, add golden tests for scenarios 4 and 5 ranking.
