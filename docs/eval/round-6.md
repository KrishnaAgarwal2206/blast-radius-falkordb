# Round 6 (independent skeptical judge)

Method: pytest (53 passed, e2e deselected), API probing, 5+ verdicts checked against data/apps and data/envs/src, UI driven with Playwright (hero, mid-run, answer, hood, Portfolio, schema), README numbers checked against data/supply/*.json, 1 LLM run (about 1.5 cents, 24 s).

## Scores
| # | Criterion | Score | Target |
|---|---|---|---|
| 1 | FalkorDB centrality | 6 | 9 |
| 2 | Correctness | 7 | 9 |
| 3 | Explainability | 8.5 | 9 |
| 4 | Demo / wow in 90 s | 8 | 8 |
| 5 | Track fit | 8 | 8 |
| 6 | Robustness | 8 | 8 |
| 7 | Performance | 8.5 | 8 |
| 8 | Setup / reproducibility (info) | 7 | - |
| 9 | Code quality / tests / README accuracy | 7.5 | 8 |
| 10 | Originality | 7.5 | 8 |

## Earlier claims re-verified
* README counts match data/supply/*.json exactly (59 alerts, 10 reachable, 5/7 possible-path, 11/8/5/1 high-critical). Number mismatch fixed.
* VEX now `under_investigation` with `proposed_status: not_affected`; fixed.
* HTTPie/pre-commit subprocess and streaming false negatives now unknown (HTTPie 0 no-path; virtualenv `not_reached`); fixed for those cases.
* CVE-id input: only a "Focus CVE-x:" prefix on the summary and a reorder of claims/actions. The full triage, plan and unrelated upgrade actions are still returned, so "focus" is cosmetic. Unknown CVE gives a clean error. In LLM mode the focus claim is not first.
* Centrality: NOT fixed (see below).

## Verdicts checked against source
1. HTTPie CVE-2024-47081 reachable: argparser.py:221 calls get_netrc_auth directly. Correct (the shown 4-hop path via prepare_request is also real).
2. pre-commit CVE-2020-14343 no path: util.py:31-32 partial(yaml.load, Loader=CSafeLoader/SafeLoader); no other yaml loads. Correct. Best result in the product.
3. cookiecutter jinja2 CVE-2024-56201 `visit_FromImport` "NO PATH FOUND": FALSE NEGATIVE. The "positive evidence" sibling is `jinja2.compiler.generate`, which builds `CodeGenerator` and calls `visit()`, which dispatches by getattr to every `visit_*`. Any `{% from x import y %}` template reaches it. The evidence offered actually proves the opposite. A VEX draft with `proposed_status: not_affected` is attached to it. Hedged wording, but it is a wrong call on an 8.8-CVSS advisory the scanner flagged.
4. cookiecutter CVE-2024-56326 "possible path" to `SandboxedEnvironment.getitem`: spurious. cookiecutter never references a sandbox (grep: none). The path goes do_sort -> make_multi_attrgetter -MAYBE_CALLS-> SandboxedEnvironment.getitem (name-based guess). Honest as "unknown" but it generates a "review manually" action on code the app does not load. Noise and a precision problem: MAYBE_CALLS is 2048 of about 5900 call edges in sc_httpie (35%).
5. cookiecutter CVE-2024-22195/34064 (do_xmlattr) and CVE-2025-27516 (do_attr) reachable: the "path" ends at `Environment.__init__` which copies the FILTERS table, so every default filter is "reachable" by construction, not invocation. CVE-2025-27516 only affects SandboxedEnvironment (not used). Known in ground-truth.md but the answer text and the headline "6 reachable (17%)" do not say so. True reachable-and-applicable is likely 3 to 4, not 6.
6. HTTPie CVE-2023-32681 4-hop and cookiecutter 8-hop (zipfile.unzip -> requests.get -> resolve_redirects -> rebuild_proxies): real code, correct.
7. Plan for cookiecutter urllib3 2.5.0: individual check installed requests 2.25.1 with urllib3 2.5.0 (requests 2.25.1 requires urllib3<1.27) and reports PASS and "1 dependent constraint satisfied". This is only valid in the combined plan. Action a3 is presented as a stand-alone pin. In HTTPie the same upgrade correctly fails. Also cookiecutter's smoke checks (`--version`, render a local template) never touch requests or urllib3, so those PASS results are vacuous. Disclosed only as "shallow".

## Other findings
* Smoke checks and the plan's findings come from the precomputed snapshot (`t_checks` reads data/supply/*.json, 0 ms). The UI step is titled "Run the app's smoke checks ... (throw-away venv)" and shows "graph-verified". It is a replay, not a run, and says so only in the data (`precomputed_at`).
* Memory claim: "previously assessed in httpie as 'reachable'. Here it is 'reachable': same advisory, different evidence." Nothing changes; memory is a lookup. The pre-commit vs yamlfull case (reachable vs no path) is the only place it matters.
* Severity inconsistency: label MODERATE with CVSS 8.8 / 7.8 (OSV label vs computed). Confusing in the headline CVE.
* Hero title "Which alerts can actually be exploited?" conflicts with the product's own "reachable is not exploitable".
* Robustness is good: empty 400, 20k+ chars 413, unknown graph 404, unknown CVE clean error, injection strings are inert (graph name validated, params bound), guard allows only read queries. Warts: `sc_memory` returns raw "investigation crashed: 'memory'"; `otel` (v1 graph) selectable but errors.
* Performance: 53 Cypher queries in about 204 ms; the answer renders in about 4 s end to end. LLM run 24 s, about 1.5 cents.
* UI: strong. Hero, live path animation, steps with "graph-verified", Portfolio showing the CVE-2020-14343 reachable-vs-no-path pair, Under the hood with per-query latency. No console errors.

## FalkorDB question: what would be lost with an in-memory graph (networkx / dicts)?
Honest answer: little of the *decision logic*.
* Reachability (`shortestPath` over CALLS): a BFS on an adjacency dict, 5k functions. Not lost; a few ms either way. The expensive and clever part (resolver: MRO, partials, class-valued params, registries) runs in Python before loading, and the edges are produced there, not by the DB.
* Upgrade planner: reads `DEPENDS_ON.spec` by dependent; a dict lookup (it also calls PyPI JSON, not the graph, for versions and requires_dist).
* PageRank/betweenness/community: only a UI lens over about 12 Service nodes; not in the verdict path.
* Genuinely degraded without a DB: (a) persistent shared `sc_memory` Decision graph across apps and sessions and the Portfolio join (a durable store, but any DB or a JSON file would do; Cypher is nice, not necessary); (b) the live "Under the hood" Cypher/latency panel and the schema view (presentation of the DB itself); (c) the guard-validated query interface that lets an LLM agent query the graph with Cypher (real, but the deterministic agent doesn't need it); (d) multi-graph isolation and zero-ops loading of 7k nodes.
* Convincing? Partly. It is a legitimate and well-used graph database use (queries are real, per-advisory, cited), and the graph-shaped problem is genuine. But "the product materially loses capability without FalkorDB" is not demonstrated: verdicts could be recomputed in 30 lines of networkx and the demo's wow moments (the two-verdict CVE, refused urllib3 bump) come from the resolver and the venv check, not from graph-database features. Centrality would rise if the resolver's inference ran in-graph (e.g. dispatch resolution as Cypher over EXTENDS/registry edges), or if a verdict visibly required a multi-hop query a dict cannot express (e.g. "which advisories become reachable if I upgrade X", computed as a graph diff).

## Top 6 fixes
1. Fix the getattr-visitor false negative: if the vulnerable function belongs to a class that is instantiated on a reached path and that class has a dispatching `visit`/getattr/registry method, emit MAYBE_CALLS to all `visit_*` methods (or downgrade to unknown/possible). Do not issue "no path found" or a not_affected VEX draft when the sibling evidence is the direct caller of that class. Add 56201 as a regression test.
2. Make the graph decisive: move one verdict-changing computation into FalkorDB and show it (e.g. dispatch resolution or "what becomes reachable/blocked after upgrading X" as a graph diff query), and show a real dependent-constraint rejection driven by a query in the demo. Today everything verdict-relevant is reproducible in networkx; this caps centrality at about 6.
3. Separate "reachable by registry table copy / wrong environment class" from invocation: tag Environment-init filter-table paths and SandboxedEnvironment-only advisories as "function present, applicability unmodelled", and drop the spurious MAYBE_CALLS to a class the app never imports (require the class's module to be imported/instantiated in the app or its deps). Report the headline as 3 to 4 reachable with caveats, not 6/17%.
4. Planner/verify honesty: run the urllib3 check only on the combined plan (or with requests bumped) and refuse a stand-alone pin that violates `requests<...`; add a check that actually exercises requests/urllib3 for cookiecutter (e.g. local HTTP server download of a zip) or label those PASS as "not exercised". Label the smoke-check step as replayed from the snapshot with its timestamp.
5. Make CVE focus real: when the input is a CVE id, answer only for it (verdict, path or evidence, its upgrade, its VEX) and collapse the rest; make the memory claim only appear when the earlier verdict differs or adds information; fix the CVSS/label mismatch; hero text "exploited" -> "reachable".
6. README/robustness polish: state the 2-class inflation (registry/sandbox) next to the 17% figure; clean errors for `sc_memory`/`otel` selection (hide non-supply graphs in supply mode); add a held-out app (not used to tune the resolver) to the benchmark so the numbers are more than descriptive.
