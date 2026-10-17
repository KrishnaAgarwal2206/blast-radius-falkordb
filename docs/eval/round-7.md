# Round 7 judge report (skeptical, fresh context)

Method: pytest (58 passed, e2e deselected); triage on all 4 apps through the API/SSE; 1 LLM run (CVE-2024-56201 on cookiecutter); direct Cypher against FalkorDB; source checks in data/apps and data/envs/src; Playwright screenshots of hero, answer, advisory click, Portfolio, Schema; robustness probes.

## Scores
| # | Criterion | Score | Target |
|---|---|---|---|
| 1 | FalkorDB centrality | 7 | 9 |
| 2 | Correctness | 8 | 9 |
| 3 | Explainability | 9 | 9 |
| 4 | Demo/wow in 90 s | 8 | 8 |
| 5 | Track fit | 8 | 8 |
| 6 | Robustness | 8 | 8 |
| 7 | Performance | 9 | 8 |
| 8 | Setup/reproducibility (info) | 8 | - |
| 9 | Code quality/tests/README accuracy | 8 | 8 |
| 10 | Originality | 8 | 8 |

## Previous issues: verified
* getattr-visitor false negative: FIXED. CVE-2024-56201 on cookiecutter is now unknown / possible_via_dynamic_dispatch (8 hops). Stale text remains in docs/eval/ground-truth.md (still says it can surface as "no path found").
* Smoke checks run with the upgrade set and are tagged (`exercises`); HTTPie urllib3 FAIL is real; cookiecutter reports a `combined: PASS`. FIXED.
* CVE focus: FIXED for ids present (CVE-2023-32681 focus returns a focused summary/actions). An id not matching the app (CVE-9999-0000, or CVE-2020-14343 on HTTPie) ends in an `error` event (recoverable:false), not an answer. With the LLM on, a non-reachable focus CVE still gets a summary that headlines "clear 3 reachable CVEs" (unrelated to the focus CVE) and calls the preflight "graph-validated API compatibility" although requests 2.32.4 was 0/0 names.
* Memory only when verdicts differ: FIXED in claims (yamlfull <-> precommit only). Step 5 still says "3 earlier decisions" for HTTPie where verdicts agree (accurate, harmless).
* Spurious paths to never-instantiated classes: PARTLY. `live` = instantiated anywhere in the loaded code (plus ancestors), so dead code in dependencies keeps classes live (requests_toolbelt's appengine adapter instantiates urllib3 contrib AppEngineManager). HTTPie's CVE-2025-66418 "possible path" is displayed through `HTTPAdapter.send -MAYBE-> AppEngineManager.urlopen -> _urlfetch_response_to_http_response -> HTTPResponse.__init__`; securetransport.WrappedSocket (macOS only) also receives MAYBE edges. The verdict stays "unknown", so no false claim, but the evidence path shown is not a real route. Liveness is not reachability-from-entry.

## Verdicts verified against source
1. pre-commit CVE-2020-14343 no path: util.py:31-32 CSafeLoader/SafeLoader via partial; only yaml_load is used in clientlib/autoupdate/migrate_config. Correct.
2. HTTPie CVE-2024-47081 get_netrc_auth reachable: argparser.py:221 calls it directly; requests sessions.py:453 prepare_request too. Correct.
3. HTTPie CVE-2023-32681 rebuild_proxies via Session.send (requests-2.26.0). Correct.
4. cookiecutter Jinja2 do_xmlattr/do_attr reachable (StrictEnvironment extends Environment, FILTERS): correct at function level; CVE-2025-27516 (SandboxedEnvironment only) is a disclosed over-reach.
5. HTTPie CVE-2025-50181: VULNERABLE_IN holds PoolManager.__init__/urlopen and ProxyManager.__init__/urlopen; the 7-hop path via HTTPAdapter.init_poolmanager is real. The UI row labels the function "urlopen" while the claim says PoolManager.__init__ (inconsistent).
6. Preflight claim: urllib3-2.5.0 source has no DEFAULT_CIPHERS (grep empty); httpie/ssl.py:6 imports it. TRUE. The graph also flags urllib3.contrib.appengine (imported by requests_toolbelt). A real, non-obvious finding, confirmed by the smoke check.
7. README numbers vs data/supply/*.json: reachable 3/6/0/1, unknown 22/18/8/0, possible-path 5/7, "28 of 59 no fix diff" (14+10+4+0) all match. 10/59 reachable.

## New problems
* Preflight is vacuous in places: it checks only `from X import name`, not attribute use (`requests.get`). cookiecutter shows "requests 2.32.4: 0/0 imported names exist" and yamlfull "0/0", presented as if validated.
* Preflight is a set-membership lookup of names per module across two graphs. A genuine two-graph query, but not graph-shaped; a dict diff gives the same answer.
* Plan, checks and Decision memory are precomputed snapshots (`P.load`; pipeline writes Decisions). An investigation only recalls memory and never writes it. The "59 decisions" count equals the alert count.
* `sc_httpie__up_urllib3` holds urllib3 2.5.0 with requests 2.26.0, not the combined planned set used by the smoke check, so the diff is per-package.
* Schema modal: node/edge labels overlap.
* HTTPie ends with CVE-2025-50181 reachable and unresolved (honest, but the story ends on "needs app change").
* Robustness is good: unknown graph 400, sc_memory and `__up_` graphs 400, empty 400, 2 MB input 413, bad JSON 422, backtick/Cypher-injection graph names rejected, injected CVE string reduced to a CVE id. Full triage 394 ms / 62 queries / 230 ms.

## FalkorDB: what is lost without it
Recomputable in networkx or dicts: every single verdict (shortestPath over ~5k functions, 3.8k CALLS, 1.6k MAYBE_CALLS), the planner's constraint lookups, centrality, the preflight name diff. Really degraded: (a) a persistent, shared, multi-process store, so Portfolio (`Decision-[:ABOUT]->Vulnerability`, 20 shared advisories, 1 verdict flip) and recall work across runs and the MCP server without rebuilding 7k-node graphs; (b) one Cypher text per claim that the UI, tests and the evidence verifier replay (path ids come from the DB); (c) many named graphs, with upgraded graphs as first-class queryable objects. This is a credible persistence + queryability + evidence argument but an operational one, not a capability impossible elsewhere; a reader can still say "Postgres or a networkx pickle would do". 7 is fair; 9 needs one outcome that only a graph query produces (fix 1).

## Top 6 fixes
1. Run reachability on the upgraded graph for the planned set and show the entry-point path that vanishes (or survives) after the upgrade. That is a graph-native decision and proves "fix clears CVE" with graph evidence.
2. Fix liveness: instantiation sites must be reachable from entry points (or exclude dead contrib modules) so MAYBE paths never route through AppEngineManager/securetransport; re-measure the possible-path counts (5 and 7).
3. Make the preflight non-vacuous: include attribute accesses, report "0 names checked" as not evaluated, and drop "graph-validated compatibility" wording when n=0 (including the LLM prompt).
4. Let an investigation write a Decision and show it in Portfolio, so memory is visibly agent-written.
5. Docs/UX hygiene: update ground-truth.md (CVE-2024-56201 now unknown), fix the urlopen vs __init__ label, return an answer card instead of a bare error for a non-matching CVE, keep focus runs from headlining unrelated upgrades.
6. UI: fix Schema label overlap and give the HTTPie story a resolution (smallest urllib3 version or app patch that passes).
