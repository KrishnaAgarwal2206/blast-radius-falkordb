# Round 3 judge report - Blast Radius

Method: read README + hackathon pages, ran pytest (36 passed, e2e deselected), drove API (127.0.0.1) and UI (Playwright, screenshots in %TEMP%\j3\shots), 3 new scenarios verified with git log/blame in data/repos/otel, 2 LLM runs (one produced an answer, one failed input resolution), temp-graph ingest (deleted).

## Scores

| # | Criterion | Score | Pass bar |
|---|---|---|---|
| 1 | FalkorDB central, multi-hop, native algos | 8.5 | 9 (miss) |
| 2 | Correctness: README 4/4 scenarios ok; new scenarios 1/3 strict (A wrong, B top-1 wrong, C right) | 5.5 | all correct (miss) |
| 3 | Explainability | 7 | 9 (miss) |
| 4 | Live demo wow | 8 | 8 (pass, barely) |
| 5 | Track fit (01 strong, 03 ok, 02 ok) | 8 | 8 (pass) |
| 6 | Robustness | 7.5 | 8 (miss) |
| 7 | Performance | 9 | 8 (pass) |
| 8 | Setup / reproducibility | 8.5 | pass |
| 9 | Code quality / tests / README accuracy | 7.5 | 8 (miss) |
| 10 | Originality | 7.5 | 8 (miss) |

## Evidence

### Correctness - new scenarios (authored from real file/line numbers)
- A: logs trace ending at sdk/_logs/_internal/export/__init__.py line 312 (`api_log_record.context = Context()` in BatchLogRecordProcessor.on_emit). `git blame` -> lines 309-315 are commit 1d9f40b5 (Ijas, "optimize LogRecord memory by removing redundant context"). Tool returned f5e0f622 (force_flush timeout defaults, touches different code), 62fcff39, 91e49a52; 1d9f40b5 absent; paged Cijo Thomas and Avinab Neogy, not Ijas. FAIL.
  Root cause (verified in graph): the function-level MODIFIED edge for on_emit lists bdb17b2c, 57fe0c15, d9467eb8, 0110bb1d only. Ingest maps each commit's historical new-side hunk line numbers (-U0) onto the CURRENT function line range. Later commits shifted lines (1d9f40b5's hunk was at 319-326 then; on_emit is 305-320 now), so attribution drifts. The README claim of SZZ-style/blame precision is not implemented for function MODIFIED edges (git log -L or blame would be needed).
- B: jaeger propagator `_extract_baggage` line 121 (`key.removeprefix`). Ground truth e52db839 (Serhiy, last edit to that line). Tool top suspect: 83f9c371 (edited `inject`, hunk at line 69, not this function), score 1.573 vs e52db839 1.557. Right commit is #2, right owner (Serhiy) paged. Top-1 wrong because file-level recency (weight 0.9) nearly ties the function-level edge (1.0) even though the graph has a Function MODIFIED edge for e52db839. PARTIAL / fail on top-1.
- C: `opentelemetry-propagator-b3` (service). Top suspect 83f9c371 (verified touches b3/__init__.py 2 lines), owners DylanRussell/Dushyant, bots excluded. PASS. But "edited the failing file" wording is wrong for a service-scope query and no impact claim at all is produced for a leaf service.
- README scenarios 1-3 reproduce exactly as written (66a7c08f; f36c1288/8acde049; view.py). Scenario 4 not re-run (memory exists: live-* incidents recalled).

### Explainability
- Each claim has a path and clicking it isolates the path in the graph (screenshot 4claim1). Deterministic claims are template-generated from the same rows, so text is supported.
- Weak spots: page claims ("owns X (0.239); authored suspect commit Y") show only the first reason's path (Person-OWNS->File), the "authored" half has no visible path. "Critical" claim shows one edge (test-utils -> sdk) as proof of "#2 by PageRank, 12 services depend on it" - the path does not support rank or count. "Similar ... similarity 1.0 your earlier investigation" is recall of an incident created by an earlier run of the same trace.
- LLM mode (run 1, 19.9 s): `finalize()` only checks that a path_id exists, never that text matches the path. LLM output "66a7c08f introduced a regression ... confirmed by incident live-64cbd71969" is circular (that incident was written by a previous run of this very trace and its CAUSED_BY was inferred then), and "Prior incident inc-66a7c08 was supposedly resolved by this same commit, but created a new failure mode", "all major exporters (OTLP, Prometheus, Zipkin, OpenCensus)" are not backed by the attached path (Incident->Commit). Page claim for Henry Chen cites a path with no Henry Chen node. This is the exact "fake/unsupported claim" risk; the README line "claims are validated against paths" overstates what is checked.
- Answer header stutters: "Interpreted your input as X. X: 14 services...".

### Demo (screenshots)
Hero is clear; mid-run shows animated traversal plus Cypher panel and live latency totals (Queries 60, 33.2 ms, p95 1.3 ms); answer has 9 claims; claim click works; lenses toggle (PageRank, Blast depth, Community render but sparse on the small answer subgraph; community lens leaves most nodes dim). Final answer graph is still busy with overlapping labels (Lukas Hering/DylanRussell). Schema modal is better but still tiny graph with overlapping edge labels (CONTAINS/ CAUSED_BY/ RESOLVED_BY cluster near Package/Incident), vast empty modal area. Memory timeline works; first cards are `live-*` entries from judging runs mixed with real history. First claim appears ~5.7 s after click due to pacing (30 ms/event) - fine for show, but a 90 s non-expert gets there.

### Robustness (API)
empty/whitespace 400; 2M chars and 20k-line trace 413 (cap 20000 chars - a legit long trace is refused rather than truncated); malformed line -> clear error; third-party only -> clear error; Java and Go -> non-Python message; prompt injection and Cypher injection strings -> "Nothing matches" (guard holds, params used); unknown graph 404 with list; missing body 422. Failures:
- Unicode/NUL input (`"Ünïcödé 💥 ✓ \x00\x01"`) -> "investigation crashed: Failed to parse query parameter 't' value" (raw internal error surfaced).
- Natural language does not work at all ("the exporter looks slow and metrics stopped exporting after the deploy", "who owns the metric reader", "what breaks if the PeriodicExportingMetricReader fails") -> "Nothing in the graph matches", also in LLM mode (fails before the LLM is called). `BatchSpanProcessor` (class name) also unresolved; only exact Service/File/Function names resolve. The previous-round NL "fix" is a rejection, not support. README honestly says "name a service, file or function", but placeholder/hero copy suggests more.
- Error paths in UI are legible (red feed line, "No answer" card).

### Performance
Deterministic: ~0.36 s end to end via curl; server `run_finished` ms 9-183. LLM: 19.86 s (one run; borderline vs 20 s target). Query latencies shown (p50 0.26 ms, p95 1.4 ms). Ingest of otel into a fresh graph: 3.3 s (README says ~10 s; conservative). Note: using `localhost` on Windows adds ~5 s per request (IPv6 fallback) - UI via 127.0.0.1 or localhost in the browser was fine.

### Setup / reproducibility
Compose pins falkordb image by digest, `requirements.lock` pinned, ingest passes `--ref` pinned SHA, ANTHROPIC_API_KEY optional with `:-` default, render.yaml + DEPLOY.md present. Not run (per instructions). Gaps: no live public deployment URL; no demo video referenced in README; hackathon requires "live deployment preferred / local + video acceptable". README lists no `.env` step issue. `docker compose run --rm ingest` writes to ./data via bind mount fine.

### Code quality / README accuracy
- pytest: 36 passed (+2 e2e deselected). README says "38 tests ... + Playwright" - double counts the e2e (38 total including e2e).
- No secrets in tree or git history (grep over `git log --all -p`; .env gitignored).
- Guard is a regex denylist but queries go through RO_QUERY - OK.
- Git history is 8 commits within ~55 minutes on 2026-10-17 (18:04-18:58 IST) - looks like a bulk generated drop; the rules require participants to explain code and disclose AI use; README has no AI-disclosure statement.
- README claims "incidents ... CAUSED_BY found by git blame on removed lines" while function-level MODIFIED uses unshifted hunk lines (see A).
- README scenario 1 says it "recalls its own fix as a past incident"; actual run shows inc-fb94553 (different) plus a live-* self-recall.

### Previous-round issues - verified status
- Cause ranking noise: improved (noisy-message damping, focus weighting, bot filtering work) but still wrong in A/B due to line drift and recency tie.
- Flaky LLM mode: one clean run (19.9 s); not stress tested.
- NL/Java guesses: Java/Go rejected properly (fixed); NL simply unsupported.
- Cluttered answer graph: better, still overlapping labels.
- Memory self-recall: NOT fully fixed - live-* incidents from prior runs appear as "Your earlier investigation ... similarity 1.0" and the LLM treats them as confirmation (circular). remember=false avoids writing but recall still reads them.
- Impact paths end at failing node: fixed (verified in S1, A, B paths end at Function/File target).
- Schema modal overlap: reduced, not eliminated.

## Bugs with repro
1. Function-level blame drift: investigate trace A (see above) -> 1d9f40b5 missing; `MATCH (c:Commit)-[:MODIFIED]->(f:Function {qname:'opentelemetry.sdk._logs._internal.export.BatchLogRecordProcessor.on_emit'}) RETURN c.sha` returns 4 commits excluding 1d9f40b5.
2. Top-1 tie: trace B, 83f9c371 outranks e52db839 despite touching `inject` only.
3. Unicode/NUL input crashes with raw FalkorDB error.
4. NL inputs unresolved (also in LLM mode).
5. LLM claims not text-verified; circular memory support.
6. Service-scope cause text says "edited the failing file".

## Prioritized fixes
1. Rebuild function-level MODIFIED attribution so it is line-accurate today: use `git log -L start,end:file` per function or run SZZ/blame at HEAD, or translate old hunks forward through subsequent diffs. Re-run scenarios A and B as golden tests.
2. Make function-level evidence dominate: when the failing function has MODIFIED edges, rank those above file-level commits regardless of recency (strict tiering), and show which lines/function each commit touched in the claim.
3. LLM-mode claim verification: require every commit sha / person / number / service named in a claim's text to appear in the attached path nodes or tool results; drop or rewrite otherwise. Exclude `source:'live'` incidents from similarity recall (or flag as "your earlier run") and never let them count as confirmation of cause.
4. Real NL support: resolve free text to nodes via keyword/fulltext index over Function/Service/File names (or let the LLM call a `find_node` tool before giving up), and fall back to a "did you mean" list; sanitize NUL/control characters before queries and never surface raw driver errors.
5. Ship the submission pieces: live deployment URL or demo video link in README, AI-use disclosure, fix test count, fix Explain paths for page/critical claims (show both owner and authored paths, show the PageRank ranking), tidy answer graph labels and schema modal layout.
