# Round 5 independent judge report

Method: read hackathon rules (FalkorDB must be central, not decorative; tracks 01/02/03), README, ground-truth.md; ran the live API/UI; 53 tests pass (`pytest --deselect tests/e2e`, 7.9 s); drove the UI with Playwright (hero, mid-run, answer, advisory click, memory, schema, mobile); checked verdicts against data/apps and data/envs/src; robustness probes; one LLM run (sc_precommit).

## Scores

| # | Criterion | Score | Target |
|---|---|---|---|
| 1 | FalkorDB centrality | 7 | 9 |
| 2 | Correctness / verification | 6 | 9 |
| 3 | Explainability | 8 | 9 |
| 4 | Demo / wow in 90 s | 8 | 8 |
| 5 | Track fit | 8 | 8 |
| 6 | Robustness | 7 | 8 |
| 7 | Performance | 9 | 8 |
| 8 | Setup / reproducibility | 7 | info |
| 9 | Code quality / tests / README accuracy | 7 | 8 |
| 10 | Originality vs prior art | 7 | 8 |

## Standard check
1. Non-obvious discovery: PASS. PyYAML 5.3.1 CVE-2020-14343 (CRITICAL 9.8) is reachable in the FullLoader app (2 hops) and no-path in pre-commit (partial(yaml.load, Loader=CSafeLoader)). Verified in source: pre_commit/util.py:31-32; FullConstructor (constructor.py:482) vs UnsafeConstructor (:725).
2. Decision changed by the graph: PARTIAL. The verdict and the upgrade scope (plan only covers `reachable`) come from graph queries, so a no-path CRITICAL gets no upgrade. But the plan ignores "unknown/possible" HIGH findings, and the verdict can be wrong (see below), so a wrong graph answer silently drops a real action.
3. Real action: PASS. Lockfile diff, PR text, smoke checks in a throw-away venv, reported separately from the fix claim; urllib3 2.5.0 refused because the checks fail (real ImportError DEFAULT_CIPHERS; httpie/ssl.py:6 imports it). HTTPie plan has no combined check (cookiecutter has one).
4. Measured improvement: PARTIAL. Real counts (59 alerts, 10 reachable, 28 with no function, matches data/supply/*.json). No held-out set, no precision/recall, no comparison with a baseline tool (OSV-Scanner call analysis, a plain networkx BFS), false positives not counted (see sandbox-only Jinja CVE below).
5. "No path found" is never equated with "not exploitable" in the text. EXCEPT the generated VEX action for pre-commit: `status: not_affected, justification: vulnerable_code_not_in_execute_path`, and the LLM review marks it "supported". That is the equation, in the machine-readable artifact.

## Verification of verdicts (against source)
- CVE-2023-32681 requests (HTTPie, reachable, 4 hops): correct (client.py -> Session.send -> rebuild_proxies).
- CVE-2020-14343 pre-commit no_path / yamlfull reachable: correct.
- CVE-2023-37920 certifi unknown: correct (data file).
- CVE-2024-35195 requests unknown/possible: reasonable.
- **WRONG (false negative) CVE-2026-97689 urllib3 `read_chunked`, HTTPie, "no path found" (HIGH).** HTTPie streams every response body: httpie/models.py:45 `self._orig.iter_content(...)` -> requests/models.py:758 `self.raw.stream(...)` -> urllib3/response.py:572 `read_chunked`. In the graph `Response.iter_content -MAYBE_CALLS-> HTTPResponse.stream` exists and `httpie.models.HTTPResponse.iter_body -MAYBE_CALLS-> iter_content` exists, but no entry point reaches `iter_body` (checked with a CALLS|MAYBE_CALLS shortestPath: empty). The core output path of the app is missing from the graph, so the verdict should be "unknown, possible path" at worst. Not in the documented failure modes (which only list getattr visitors and plugins).
- **WRONG-ish (false negative class) pre-commit virtualenv x5 "no path found" (CVE-2026-102930/38/37/22702 ...).** pre-commit executes virtualenv through `[sys.executable, '-mvirtualenv', envdir]` (languages/python.py:195; also `-mnodeenv` in node.py:93). Subprocess/`-m` execution is a core runtime path and is invisible to a static call graph; virtualenv's `download_wheel` / `_run_manual_upgrade` (seed/wheels) run on every env creation. The answer counts these under "no path found" without flagging the subprocess blind spot. This is exactly the class where "no path" misleads.
- Over-claim (false positive in exploitability terms): cookiecutter CVE-2025-27516 `do_attr` "reachable". The advisory only affects `SandboxedEnvironment`; cookiecutter uses a plain `Environment` subclass (environment.py:55). Disclosed generically ("reachable != exploitable") but a precondition that is readable from the same graph (EXTENDS Sandboxed?) is not used.
- CVE-2025-50181 "reachable" via `PoolManager.__init__`: trivially always executed; the advisory is about a non-default `retries` setting. Reachability of an `__init__` is weak evidence (ground-truth case 8 admits it).

## Other defects
- README line 23 says HTTPie has "4 reachable advisories out of 25"; data, UI, table, and live API all say 3. (DEMO_SCRIPT says "four hops", fine.)
- Free-text input is ignored: `"CVE-2020-14343"` on sc_precommit, and an injection string, both return the same generic triage; a CVE id does not focus the answer. (Injection is harmless: the input never reaches a prompt or Cypher in deterministic mode.) The textarea placeholder invites a CVE id.
- Action a5 ("manually review CVE-2025-47273") cites path `reach13`, an unrelated path (evidence mis-attachment that the claim verifier accepts).
- Smoke-check failure text leaks a local Windows path (`C:\Users\KRISHNA\OneDrive\...`) in the answer and the UI.
- Memory demo is weak: the HTTPie run recalls "reachable here, previously reachable in cookiecutter: same advisory, different evidence", which is the same verdict. The pre-commit recall cites the synthetic `yamlfull` control as a prior "decision". All 59 decisions are written by the product's own batch, so memory is not evidence of learning. `unblocked_by` is always `[]` in shipped data, so the README's "urllib3 2.x blocked until requests is bumped" multi-step planner story is never shown (the code path exists and is unit tested).
- Plan scope is `reachable` only; HTTPie's urllib3 2.5.0 leaves 6 urllib3 findings (several HIGH) open. Disclosed in `remaining`, not in the summary line.
- UI: the Schema modal is cluttered/illegible and lists v1 labels with 0 counts (Commit, Person, Incident, Decision, Package); the legend still shows v1 labels. Final answer panel is long; mobile is hero-only.
- `judge4_tmp` and `otel` graphs are listed by the unknown-graph error (information leak, minor; `judge4_tmp` is a leftover).
- Timing: deterministic run 255 ms, 53 FalkorDB queries 201 ms total (p95 34 ms); LLM run 12 s. Ingest not timed (needs network, README says "a few minutes"). OSV is fetched live at ingest, so advisory sets (several `CVE-2026-*` ids already) will drift from the committed JSON; the Docker image copies data/supply but ingest regenerates it.

## What breaks without FalkorDB
Reachability (shortestPath over 5k functions), the `DEPENDS_ON{spec}` lookup, and Decision recall. Honest assessment: the shortestPath could be a networkx BFS and the planner's graph read is a single-edge-property lookup (`MATCH (d)-[e:DEPENDS_ON]->(p) RETURN e.spec`) that a dict does as well; memory is a keyed store. PageRank/community lenses are decorative for the verdict. The strongest FalkorDB-specific idea is the call-site-sensitive resolver edges plus EXTENDS reasoning, but those are computed in Python before loading. So the product loses its demo but not its algorithmic core without the DB. Centrality is real but not irreplaceable. To score 9, make a decision that only a multi-hop graph query can make (e.g. combined reachability + constraint + ownership in one query, incremental re-query after an upgrade over the stored graph, graph diff between lock versions).

## Originality
Reachability-for-SCA is established (OWASP VulnReach, OSV-Scanner call analysis for Go/Java, Endor Labs function-level reachability, Snyk, Semgrep SSC). Differentiators here: Python cross-package with type-flow dispatch, fix-diff to function mapping, honest tri-state verdicts, upgrade plan with constraint graph plus actually running smoke checks, cross-app memory. Still no comparison against OSV-Scanner or pip-audit; "nobody does this" cannot be claimed.

## Prioritized fixes
1. Fix or disclose the HTTPie body-streaming false negative (`iter_body` unreachable); add a guard test and re-run the verdict. Make "no path found" downgrade to "unknown, possible path" when a MAYBE_CALLS chain exists into the same class/file, and add this failure mode to ground-truth.md.
2. Model subprocess/`-m module` execution (`[sys.executable, '-mvirtualenv']`, `subprocess` of a package's console script) as entry edges to the dependency's `__main__`/entry, or flag "package is executed as a subprocess" and mark those verdicts unknown instead of no-path (virtualenv x5 in pre-commit).
3. Stop emitting VEX `not_affected` from a static no-path verdict; use `under_investigation` or a clearly-labelled "no static path" status, and make the LLM reviewer reject it.
4. Correct README (4 -> 3 reachable) and add a gate that regenerates README numbers from data/supply/*.json in CI.
5. Make FalkorDB indispensable: add a graph-only decision (incremental reachability delta after the planned upgrade by re-querying a versioned graph, or `EXTENDS`-based precondition such as SandboxedEnvironment), and benchmark against an in-memory BFS/OSV-Scanner to show what the graph adds. Report a precision/recall table with manually labelled sample (even 30 advisories).
6. Use the input: a CVE id / package name should focus the answer; evidence mis-attachment (a5 -> reach13) must be rejected by the claim verifier.
7. Demo polish: make memory show a changed decision (verdict differs between apps with different evidence, not a synthetic control); show a multi-step unblock in the planner; sanitize paths in check output; clean the Schema view and v1 legend labels; add a combined smoke check for HTTPie.
8. Reproducibility: pin OSV snapshot (commit raw advisory JSON) so ingest reproduces the numbers; time the ingest and put it in the README; replace the placeholder live URL and demo video before submission; remove stale `judge4_tmp`/`otel` from the public graph list.
