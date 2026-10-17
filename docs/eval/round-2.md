# Blast Radius - independent judge, round 2

Method: pytest (34 passed, 28 s), API probing (remember:false), 2 LLM runs (about $0.04 total), Playwright screenshots, re-ingest into judge2_tmp (3.0 s, deleted), source reading.
Note: running pytest rewrites the git-tracked tests/e2e/shots/*.png (dirty tree after tests). I restored them with git checkout.

## Scores
| # | Criterion | Score | Pass bar |
|---|---|---|---|
| 1 | FalkorDB central, graph drives decisions, multi-hop + algos | 8.5 | 9 - miss |
| 2 | Correctness | README 4/4; new scenarios 1/3 correct | all - FAIL |
| 3 | Explainability | 7 | 9 - miss |
| 4 | Live demo wow (90 s) | 8 | 8 - pass (marginal) |
| 5 | Track fit | 8.5 | 8 - pass |
| 6 | Robustness | 6.5 | 8 - miss |
| 7 | Performance | 9 | 8 - pass |
| 8 | Fresh-clone setup / reproducibility | 7 | - |
| 9 | Code quality / README accuracy | 7.5 | 8 - miss |
| 10 | Originality | 8 | 8 - pass |

## Previous-round findings: fixed?
- Formatting commits ranked first: fixed for the README scenarios (66a7c08f, f36c1288, 8acde049, 8c870181 on top). NOT fixed in general: caller-frame files dominate (below).
- Flaky LLM mode: fixed. Both llm:true runs completed (16.7 s and 19.4 s, $0.022 and $0.0175), right at the 20 s target. LLM is a reviewer over a deterministic draft (pipeline runs first), not a free tool-router; README's "LLM only routes between tools" overstates it. In the SimpleSpanProcessor run it honestly said the suspects "are not direct causes" but still did not find the real one.
- NL input: partly. "what breaks if the opentelemetry-semantic-conventions package changes?" works. "Why is the metrics exporter dropping data? ... periodic reader" resolves to opentelemetry-exporter-otlp with 0 impact. A Java trace resolves to semconv thread_attributes.py (token "thread") and reports 15 dependent services: a confident wrong answer.
- Cluttered answer graph: improved (hero/answer screenshots readable), a few overlapping labels remain; schema modal has overlapping edge labels and a clipped Function node.
- Memory self-recall: labelled honestly ("Your earlier investigation ... similarity 1.0") but it still takes the top similar slot, so scenario 1's "recalls its own fix" is recalling a previous live run, not the real fix commit. Repeated demos pollute memory (62 incidents incl. UI runs).

## 2. Correctness evidence
README scenarios verified against git in data/repos/otel: S1 origin SynchronousMeasurementConsumer.collect, 14 svc / 25 files, top 66a7c08f - OK. S2 grpc exporter f36c1288, 8acde049 - OK. S3 view.py 14/24, 8c870181 top - OK. S4 memory recall - OK (self record).

New scenarios (traces authored from real file/line numbers; expected via git log -L and pyproject):
1. Trace through SimpleSpanProcessor.on_end (export/__init__.py:126, caller trace/__init__.py:995, plus a vendor frame). Origin correct. Expected cause a6d59ca63 or 91e49a52c (git log -L on on_end). Got top-3 3701d6b1, 5d9d4cc5, 5321c606 (all touch trace/__init__.py, the caller frame; 5321c606 is "docs: remove stale TODO"); 91e49a52 ranked 5th, a6d59ca63 absent. FAIL. Claim text says "edited the failing file" while the path shows a different file.
2. Trace through BatchLogRecordProcessor.on_emit (export/__init__.py:320, caller _logs/_internal/__init__.py:516). Expected 1d9f40b5a (git log -L 305,321). Got 9579280b "Add return type annotations to MultiLogRecordProcessor" top (caller-frame file); 1d9f40b5a absent. FAIL.
3. Service opentelemetry-propagator-b3 (no dependents per pyproject grep): 0 services / 0 files - CORRECT. semconv: only sdk depends directly, 15 transitive plausible. Pass, though no explicit "nothing depends on this" claim and a "most likely cause" is still emitted when nothing failed.
Root cause: suspect_changes seeds = every frame's file; file-level MODIFIED scoring ignores which function the frame is in, although 2,378 function-level MODIFIED edges exist. Evidence paths for causes are File-level only ("66a7c08f -MODIFIED-> file").

## 3. Explainability
All claims carry path ids that exist and clicking highlights them. But: impact claims show the 3 closest paths, all 1-hop, and they do not connect to the failing node (e.g. "opentelemetry-configuration -DEPENDS_ON-> opentelemetry-sdk" offered for a Function-level blast radius). Of 61 paths in S1, 36 are single edges (13 two-hop, 12 three-hop exist but are not the ones displayed). Cause claims say "edited the failing file" for files that are only caller frames (S1: eee0da65 modifies export/__init__.py). LLM claims add unsupported prose ("including all OTLP, Zipkin, OpenCensus exporters", "check if fix from that incident regressed"): verification is "path id exists", not "text supported".

## 6. Robustness
OK: empty 400, >20k 413, unknown/empty graph 404 JSON, malformed body 422, garbage traceback clean error, third-party-only trace clean error, gibberish shows red "No answer" box in UI, injection text ignored (resolved opentelemetry-sdk; reads are RO_QUERY).
Bad: Java trace -> confident wrong answer; NL question -> wrong service. No confidence threshold on fuzzy token resolution.

## 7. Performance
Deterministic: server 57-200 ms per investigation, 60 queries / 28 ms FalkorDB time; p50 0.22 ms / p95 1.2 ms over 1453 queries; shown in UI. LLM: 16.7-19.4 s. Ingest 3.0 s for 3,657 nodes / 9,769 edges (README says about 10 s: conservative). judge2_tmp deleted.

## 8. Setup
Dockerfile/compose sane; ingest pinned to a commit SHA; volume for FalkorDB. Gaps: falkordb/falkordb:latest unpinned; requirements.txt uses >= with no lock; ingest requires github.com (no offline path other than a local clone); replays make the UI demo work offline. Not run (per instructions), so "works first try" is unverified.

## 9. Code quality
Clean layers, 34 tests (README says 31: stale). Golden tests only cover README scenarios, which is why the caller-frame bug passes. No secrets in tree or history (git log -p grep clean; .env ignored). e2e test overwrites tracked screenshots. In-memory RUNS dict and per-run replay files.

## 10. Originality
Incident forensics (trace -> function -> commit/SZZ-lite -> owner -> memory) with a live Cypher/latency panel differs from Code-Graph (browsing), Sourcegraph (search), Backstage (catalog), incident.io (workflow). Weakness: positioned as a general agent but is a fixed pipeline plus LLM reviewer; one repo only.

## Prioritized fixes
1. Rank suspects by function-level evidence: for a trace, score MODIFIED edges to the failing Function (and callees) first; down-weight caller-frame files heavily; drop docs/format/type-annotation commits. Add golden tests for on_end (a6d59ca63/91e49a52c) and BatchLogRecordProcessor.on_emit (1d9f40b5a).
2. Make claim text match the path: say "edited X, a caller N frames up" and render the real multi-hop path (failing node to impacted) for impact claims; verify numbers/names in LLM claim text against path data, not just id existence.
3. Input confidence gate: reject/ask when only a generic token matched (thread, exporter); detect non-Python traces (Java "at com.x.Y(File.java:N)") and say so; for NL show "interpreted as X".
4. Memory hygiene: dedupe/exclude the user's own live incidents from the similar slot or show the historic fix first; add a reset-demo-memory control; align README scenario 4.
5. Reproducibility: pin the falkordb image tag, add a lock/constraints file, make e2e screenshots go to a tmp dir, fix README test count.
6. Polish: schema modal overlap/clipping; claim-click should frame the full path; stream the deterministic answer first and let the LLM review land after (keep LLM under 15 s).
