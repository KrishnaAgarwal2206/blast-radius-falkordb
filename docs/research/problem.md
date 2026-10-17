# Blast Radius: Problem, Prior Art, Demo Target

## 1. Why the problem matters
| Claim | Source |
|---|---|
| "SRE has found that roughly 70% of outages are due to changes in a live system." (verified by fetch) | Google SRE Book, Introduction: https://sre.google/sre-book/introduction/ |
| Avg incident ~175 min to resolve; downtime est. $4,537/min; responders hindered by "fragmented IT environments... inability to identify the right responders" | PagerDuty 2024 survey: https://www.businesswire.com/news/home/20240627388939/en |
| DORA 2024 (39k+ respondents): failed-deployment recovery time elite <1h, high <1 day, medium 1 day-1 week; change-failure rate elite ~0-15% | https://dora.dev/research/ ; summary https://rdel.substack.com/p/rdel-68-what-are-the-latest-benchmarks |
| Real postmortem corpus to cite recurrence of change-caused failures | https://github.com/danluu/post-mortems |

Pitch line: Google SRE reports ~70% of outages are change-induced, so "which recent change touched the failing path, and who owns it" is the highest-yield first question, yet today it is answered by humans grepping git blame, Slack and wikis. Caveats: the 70% is Google's experience, not an industry average. There is no solid public stat for "time spent finding the owner"; do not invent one, use the PagerDuty "right responders" quote.

## 2. Prior art and gaps
| Tool | Does well | Falls short for this use case |
|---|---|---|
| Sourcegraph (https://sourcegraph.com) | Code search, cross-repo navigation | No incident/ownership/change-history graph; returns hits, not reasoned paths |
| CodeQL (https://codeql.github.com) | Deep dataflow/call queries | Security-oriented, heavy DB build, no git history or people |
| GitHub dependency graph (https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-the-dependency-graph) | Package-level deps, Dependabot | Package granularity only; no function level, owners, or incidents |
| Backstage / OpsLevel / Cortex (https://backstage.io, https://www.opslevel.com, https://www.cortex.io) | Service catalog, ownership, dependencies | Hand-maintained metadata drifts; service-level only; no stack-trace entry point |
| PagerDuty / incident.io / Rootly (https://www.pagerduty.com, https://incident.io, https://rootly.com) | Paging, timelines, AI summaries, similar incidents, deploy correlation | Not grounded in code structure; routes by schedule/service tag, not by who changed the failing function |
| Code-graph RAG OSS: FalkorDB/code-graph (https://github.com/FalkorDB/code-graph, https://docs.falkordb.com/genai-tools/code-graph), vitali87/code-graph-rag, Neo4j code-KG demos | Parse code into a graph, chat over it | Structure only: no commits/people/incidents/ownership, no deterministic ops; generic "chat with your repo" |
| Hackathon precedent | FalkorDB "Memory Meets Motion" (Aug 2026) winner Atrium modeled student misconceptions as graph nodes (https://www.plushcap.com/content/falkordb/blog/falkordb-memory-meets-motion-the-falkordb-standouts). I found no verified code-graph/incident-agent winners; do not claim any | Space is open |

## 3. Differentiation
| Capability | Sourcegraph | Backstage | PagerDuty/incident.io | FalkorDB code-graph | Blast Radius |
|---|---|---|---|---|---|
| Code-level structure | yes | no | no | yes | yes |
| Git change history in graph | no | no | partial (deploys) | no | yes (commit -> file/function) |
| Ownership from reality | no | manual | schedule | no | CODEOWNERS + recency-weighted authorship |
| Stack trace -> blast radius -> suspect -> who to page | no | no | no | no | yes, one tool chain |
| Past-incident recall | no | no | text similarity | no | graph similarity (shared nodes) + optional semantic |
| Every claim shows its path | no | no | no | partial | yes (explain_path, highlighted live) |

### Do
- Deterministic tools (parameterized Cypher in Python) compute answers; the LLM chooses tools and narrates. Every tool returns `{answer, paths[]}`; the UI highlights those paths.
- Few high-level tools plus a guarded read-only Cypher escape hatch.
- Real data only: real repo, real commits, real fix PRs as seeded incidents. Label anything synthetic.
- Render only the answer subgraph (<=60 nodes), package-level by default, expand on click.
- Pre-ingest and snapshot the graph; the demo must not depend on live ingestion.

### Do NOT
- Let the LLM write Cypher unguarded. Use `GRAPH.RO_QUERY`, deny write/admin keywords, force LIMIT and timeout, cap result size.
- Use the graph as a vector sidecar; traversal must do the reasoning.
- Show the whole-repo hairball.
- Fake data or invent incidents.
- Over-scope: Python only, `ast` only, no cross-language, no type-resolved call graph. CALLS is best-effort name resolution; mark edge confidence.

## 4. Demo target repos (inspected by blobless clone, 2026-10-17)
### Primary: open-telemetry/opentelemetry-python (https://github.com/open-telemetry/opentelemetry-python)
- 2,381 commits, 389 in 2026; 111 distinct authors in the last year; pushed today; 817 .py files; blobless clone ~8 s. Ingest should be well under 2 min (ast on ~800 files; `git log --name-status` bounded to ~12 months).
- Natural "services" are ~30 independently versioned packages with their own pyproject: api, sdk, proto, semantic-conventions, configuration, exporter/* (14), propagator/* (b3, jaeger), shim/*. Declared pyproject deps give real DEPENDS_ON edges, e.g. exporter-otlp-proto-grpc -> api, sdk, proto, otlp-common, otlp-proto-common; exporter-otlp-proto-http also -> exporter-http-transport. Internal imports are dense (`opentelemetry.sdk` imported 122 times inside sdk src).
- Ownership caveat: `.github/CODEOWNERS` exists but is a single catch-all (`* @open-telemetry/python-approvers`). Ownership therefore comes mainly from authorship (recency-weighted commit share per package), which is itself a selling point ("ownership from reality"). Top authors last year: Lukas Hering 50, Mike Goldsmith 45, Riccardo Magliocchetti 41 (bots to be excluded).
- Real incident seeds (fix commits with PR numbers): 66a7c08f (metrics collection timeout / MetricsTimeoutError), d9963311 (thread leak in resource init), 37f6c925 (NaN in TraceIdRatioBased), 8acde049 (OTLP gRPC endpoint path), f36c1288 (invalid timeout env vars), 199b5718 (prometheus port env var).

### Secondary (only if time): Netflix/dispatch (https://github.com/Netflix/dispatch)
5,279 commits, 457 since 2025-01, 717 .py, 92 authors, last push Sep 2025. `.github/CODEOWNERS` lists 4 individuals on one line. Monolith with domain subpackages under src/dispatch (top internal imports: database 191, plugins 149, project 126, incident 124); "service" = top-level subpackage. Thematic fit but stale and weaker services story. Use OTel first.

### Three scenarios (re-verify with `git log`/pyproject at the pinned ingest commit and freeze the expectations into a test)
1. Service down: "opentelemetry-exporter-otlp-proto-grpc fails at startup on a bad timeout env var". Expect: blast radius = packages that DEPEND_ON it (e.g. the opentelemetry-exporter-otlp meta-package; confirm in pyproject); top suspects f36c1288 (2026-10-07, Y-C) and 8acde049 (2026-10-01, Shriprasad R Patil), both touching exporter/opentelemetry-exporter-otlp-proto-grpc/src; page = top recency-weighted author of that package; similar past incident: other env-var parsing fixes (199b5718).
2. Change impact: "I am changing opentelemetry-sdk/src/opentelemetry/sdk/metrics/_internal/view.py". Expect: importers in sdk.metrics, then every package depending on sdk (all exporters); recent commits 8c870181 (Erin, 2026-10-08), cee5f52e (2026-09-29), 2e3b7d8a (2026-08-13) all concern View instrument-name matching, flagging a recurring-defect hotspot; the three fixes are the SIMILAR_TO cluster.
3. Stack trace: a real trace through `opentelemetry/sdk/metrics/_internal/export/__init__.py` (periodic reader collection timeout). Generate it authentically by running a tiny script against the checked-out repo with a deliberately slow observable callback. Expect trace_stacktrace to map frames to Function nodes, deepest in-repo frame = origin, top suspect 66a7c08f, recalled incident d9963311 at lower similarity.
