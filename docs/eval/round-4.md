# Round 4 judge report (independent)

Tests: 39 passed (non-e2e). Ingest into temp graph judge4_tmp: 4.5 s (README says ~10 s). Deterministic run: 0.16 s server-side, 0.6 s end to end (a ~4.7 s figure seen with `localhost` is Windows IPv6 fallback in my client, not the product). LLM run: 13.6 s.

| # | Criterion | Score |
|---|---|---|
| 1 | FalkorDB central, multi-hop, native algos | 9 |
| 2 | Correctness (README 2/2 checked, 4 new 4/4) | 8 |
| 3 | Explainability | 8 |
| 4 | Live demo wow | 8 |
| 5 | Track fit | 8 (01 strong, 03 ok, 02 thin) |
| 6 | Robustness | 8 |
| 7 | Performance | 9 |
| 8 | Setup / reproducibility | 7 |
| 9 | Code quality / tests / README accuracy | 8 |
| 10 | Originality | 8 |

## New scenarios (all verified with git)
- A: traceback at BatchLogRecordProcessor.on_emit line 311 -> top cause 1d9f40b5 (git blame: Ijas) correct; page Ijas flagged inactive.
- B: service `opentelemetry-propagator-b3` -> 83f9c371 (Dushyant Acharya, 2026-10-08) correct; no impact claim (no dependents).
- C: file sampling.py -> 37f6c925 (verified touches file) top; impact 14 svc / 41 files.
- D: otlp-proto-http _log_exporter line 186 -> 89cc68b9 (blame) top, 6810d3d7 and 5f851d2a (verified touches file) listed.
README scenario 1 (66a7c08f, 14/25) and 3 reproduce.

## Findings
- Circular "similar past incident": for A, B, C the incident recalled with similarity 1.0 is the suspect fix commit itself (inc-1d9f40b, inc-83f9c37, inc-d5a8cec). Not independent evidence.
- Memory is 60 of 61 mined git fix commits; only 1 "live" incident. Track 02 is thin.
- LLM run (D): called 6810d3d7 "Root cause" although deterministic score/blame favour 89cc68b9; narrated my invented "9MB" message; "similar" claim (inc-eee0da6, fork TypeError) described as "also involving SDK-level error handling", which its path (Incident->File) does not support. Claim verification checks ids, not semantics.
- LLM mode does not rescue natural language: NL input is rejected before the LLM even with llm:true.
- Deterministic NL ("why is the metrics exporter timing out") gives no did-you-mean; did-you-mean suggestions are file paths, not services.
- "14 dependent services" for nearly any sdk change: low discrimination. "opentelemetry-sdk #2 SPOF" critical claim appended to unrelated answers.
- Lenses are visually inert after a claim focuses the graph (screenshot: PageRank/Community show same 2-node path). Schema modal edge labels still overlap in the centre.
- README: Live demo and Demo video are placeholders, both required deliverables; docs/queries.cypher exists.
- Robustness: Java/Go/malformed/third-party/empty (400)/20k+ (413)/injection/Cypher-injection/control chars/unknown graph (404) all handled cleanly; no console errors.
- No secrets in tree or history (.env ignored, key empty in .env.example).

## Top fixes
1. Publish live URL and demo video.
2. Exclude the suspect commit's own incident from "similar" (or label as "this fix"); add real cross-session memory demo.
3. Semantic check of LLM claims (cause ordering vs scores, similar-claim text vs path) or label LLM override.
4. Make lenses apply to the claim-focused graph / unfocus on lens click; declutter schema labels.
5. NL: route to LLM entity resolution or suggest services; reduce repeated SPOF claim.
