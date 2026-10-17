# Round 8 judge report (skeptical, fresh context)

Verified: pytest 60 passed (e2e deselected). UI driven with Playwright (hero, answer, portfolio, no console errors); triage on HTTPie renders in about 4.5 s, 62 FalkorDB queries, 360 ms DB time. Two LLM-free runs on CVE ids plus one LLM run (CVE-2025-50181, 20 s, $0.013).

## Verified against source
- urllib3 2.5.0 has no DEFAULT_CIPHERS (grep empty); urllib3 2.5.0 has no contrib/appengine; requests_toolbelt 0.9.1 `_compat.py:50` imports `urllib3.contrib.appengine`. Preflight "2 missing" is true.
- Paths: CVE-2023-32681 (Session.send -> rebuild_proxies, sessions.py:636), CVE-2025-50181 (HTTPAdapter.__init__ -> init_poolmanager -> PoolManager), CVE-2024-47081 (prepare_request -> get_netrc_auth, sessions.py:453), precommit PyYAML no-path, cookiecutter jinja2 reachables: all consistent with source.
- README bench numbers match data/supply/*.json counts (3/6/0/1 reachable; 25/24/9/1).
- LLM patch is sensible (drop the removed import, DEFAULT_SSL_CIPHERS = None) but it also rewrites a curly apostrophe in a comment (noise) and changes the `--ciphers` help text default to "None".

## New problems found
1. **The "verified fix path" was never tested on the combination it recommends.** requests 2.26.0 declares `urllib3<1.27`. The smoke checks (both the failing urllib3 check and the passing LLM-patch check) install requests 2.26.0 + urllib3 2.5.0 (`--no-deps`; the check output shows requests' own "urllib3 doesn't match a supported version" warning). The planner only allows urllib3 2.x because requests is also bumped to 2.32.4, yet the check, the `up_urllib3`/`fix_urllib3` graphs and the patch action (`pip install urllib3==2.5.0 requests-toolbelt==1.0.0`) leave requests at 2.26.0. The re-analysis ("0 reachable, was 3", graph `up_fixed`) uses requests 2.32.4 + urllib3 2.5.0 + toolbelt 1.0.0, a set that no smoke check ran. The claim "smoke checks PASS on that combination" is therefore inaccurate. `unblocked_by` is empty although the urllib3 upgrade only becomes legal after the requests upgrade.
2. Recommended pip command conflicts with requests 2.26.0 under a real resolver.
3. Conservative false unknowns: idna CVE-2024-3651 (idna.encode is called by urllib3.util.url, url.py:297-305) is "unknown / no fix mapping"; 28 of 59 advisories have no function mapping. Safe direction, but it caps usefulness (3 of 25 HTTPie).
4. Known false positive stays: Jinja2 CVE-2025-27516 (sandbox-only) reported reachable for cookiecutter; disclosed in ground-truth, not in the UI.
5. Portfolio "verdicts differ" shows only one such CVE (the staged PyYAML pair); the cross-app memory mostly shows identical verdicts, so the Decision recall rarely changes a decision.
6. Unknown CVE id gives a clear error event (fine); the injection string was parsed to the first CVE id and no Cypher ran (fine); empty, 200k input, unknown graph, sc_memory and sc_httpie__up_urllib3 give clean 4xx.

## FalkorDB argument
Real: two-graph preflight diff (is the strongest piece; names imported by the app and by other dependencies vs the upgraded graph), constraints on DEPENDS_ON edges, persistent Decisions/Portfolio, live Cypher panel, 7k-node graphs with ~1 ms shortestPath. Still true that a single run could be done with networkx plus a dict diff; what is lost without the DB is persistence/sharing across processes and the inspectable Cypher story, not capability of any one verdict. Better than earlier rounds, but not irreplaceable.

## Scores
| # | Criterion | Score | Target |
|---|---|---|---|
| 1 | FalkorDB centrality | 7.5 | 9 |
| 2 | Correctness | 7 | 9 |
| 3 | Explainability | 8.5 | 9 |
| 4 | Demo/wow in 90 s | 8 | 8 |
| 5 | Track fit | 8.5 | 8 |
| 6 | Robustness | 8.5 | 8 |
| 7 | Performance | 9 | 8 |
| 8 | Setup/reproducibility (info) | 7 (live URL/video pending) | - |
| 9 | Code quality/tests/README accuracy | 7.5 | 8 |
| 10 | Originality | 8 | 8 |

## Top fixes
1. Smoke-check, preflight and re-analyse the SAME full set (requests 2.32.4 + urllib3 2.5.0 + toolbelt 1.0.0 + patch); make `upgrade_set`/`unblocked_by` include requests; make the `pip install` command include requests==2.32.4.
2. Reword "checks PASS on that combination" and "0 reachable (was 3)" until fix 1 is done; state that the re-analysis graph differs from the tested set.
3. Run the pip resolver (not just `--no-deps`) in the check venv and report dependency-constraint violations as failures.
4. Strip noise from LLM patches (the apostrophe change) and flag semantic changes (DEFAULT_SSL_CIPHERS None alters help text/behaviour).
5. Map more advisories (idna, urllib3 fix commits) or surface the unknown-share (28/59) prominently in the UI headline.
6. Make cross-app memory change a decision visibly (e.g. reuse a verdict to skip work or flag a disagreement) beyond the staged PyYAML pair; add an informal benchmark of what networkx would not persist.
