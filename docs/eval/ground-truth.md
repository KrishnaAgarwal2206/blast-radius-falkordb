# Ground truth, method and known failure modes

What is measured, how, and where it is wrong. Nothing here is a benchmark against a labelled dataset (none exists for Python function-level reachability); it is a set of hand-checked cases plus controls, with the failure modes listed.

## Method in one paragraph
For each app (a real OSS project at a real tag, with the dependency versions an unrefreshed lock would pin) we fetch every pinned distribution's Python source from PyPI, parse app and dependencies with `ast`, resolve calls across packages (imports and re-exports, inheritance, `self`/`super()`, local `x = Cls()` types, constructor calls, class-valued parameters per call site, `functools.partial`, handlers registered on classes, handler tables) and load everything into FalkorDB. Advisories come from OSV for the pinned versions. OSV does not say which function is vulnerable, so we take the functions changed by the advisory's **fix commit** (from the hunk contents; for module-level changes, the handlers the commit stopped registering). Then, per advisory: strict `CALLS` path from an entry point to a vulnerable function = **reachable**; a path only through `MAYBE_CALLS` (unresolved dynamic dispatch) = **unknown, possible path**; none = **no path found** (if a function was identified) or **unknown** (if not).

## Hand-verified cases

| # | Verdict produced | Evidence checked by hand | Outcome |
|---|---|---|---|
| 1 | HTTPie 2.6.0: `requests` CVE-2023-32681 **reachable**, 4 hops `core.main -> core.program -> client.collect_messages -> Session.send -> SessionRedirectMixin.rebuild_proxies` | `httpie/client.py:102` calls `requests_session.send(...)`; `requests-2.26.0/requests/sessions.py:636` `send` calls `self.rebuild_proxies(...)`, `:676` calls `self.resolve_redirects(...)` | Correct (function reachable) |
| 2 | pre-commit 2.9.0: PyYAML 5.3.1 CVE-2020-14343 **no path found** | `pre_commit/util.py:31-32`: `Loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)`; `yaml_load = functools.partial(yaml.load, Loader=Loader)`. The fix commit moved the `python/object` handler registrations from `FullConstructor` to `UnsafeConstructor`; `SafeConstructor` never had them | Correct for this version and configuration |
| 3 | `yamlfull` control: same CVE **reachable**, 2 hops | The app calls `yaml.load(f, Loader=yaml.FullLoader)`; `FullConstructor` has the three handlers registered in 5.3.1 | Correct (positive control) |
| 4 | cookiecutter 1.7.3: Jinja2 CVE-2024-22195 `do_xmlattr` **reachable** | cookiecutter renders user-supplied templates with `jinja2.Environment`; `Environment.__init__` copies the filter table `FILTERS` that contains `do_xmlattr` | Correct as "reachable function"; exploitation needs a template (or attribute keys) that uses `\|xmlattr`, which the analysis does not model |
| 5 | certifi CVE-2023-37920 **unknown** | The fix removes root certificates from `cacert.pem`; no Python function changed | Correct to refuse a call-path claim |
| 6 | virtualenv CVE-2024-53899 **unknown** | The fix edits shell activation scripts, not Python functions | Correct |
| 7 | HTTPie: `requests` CVE-2024-35195 (`HTTPAdapter.send`) first came out **no path found**, which is wrong: every request goes through `adapter.send(...)` where `adapter = self.get_adapter(url)` | Found by reading `Session.send` | **Wrong, now fixed** by `MAYBE_CALLS`: it is reported as *unknown, possible path* |
| 8 | HTTPie: `urllib3` CVE-2025-50181 **reachable** (`PoolManager.__init__` via `HTTPAdapter.init_poolmanager`) | Code path is real; the advisory needs a non-default `retries` setting for the exposure | Reachable function, exploitability unknown |

## Bugs found by this process (and fixed)
* Hunk headers attribute a change to the *preceding* def (CVE-2025-27516 was first mapped to `do_reverse`; it is `do_attr`). Mapping now follows changed lines to their enclosing def.
* PyYAML's fix is module-level (handler registration), so function-body mapping found nothing; the mapping now reads removed registration lines.
* `super()` inside a mixin never resolved (cookiecutter's `ExtensionLoaderMixin`); it now continues along a subclass's MRO.
* `Cls().method()` and star imports (`from .loader import *`) were not resolved.
* A plain call graph says "no path" even for a vulnerable `FullLoader` app, because `yaml.load` instantiates a class passed as a parameter; hence the call-site-sensitive edges and the positive control.

## Found by an independent judge and fixed
* HTTPie's `urllib3` CVE-2026-97689 (`read_chunked`) was "no path found", but HTTPie streams every response body through `iter_content -> raw.stream -> read_chunked`; those hops are dynamic and the entry point never reached `iter_body`. **Fix:** "no path found" now requires positive evidence (the app reaches other code in the same file); otherwise the verdict is "unknown (not reached)". HTTPie went from 3 "no path" to 0.
* pre-commit launches `virtualenv` and `nodeenv` as subprocesses (`[sys.executable, '-mvirtualenv', ...]`), which a static call graph cannot follow. The five virtualenv advisories are now "unknown (not reached)" instead of "no path".
* The generated VEX draft said `not_affected` from a static result. It now says `status: under_investigation`, with `proposed_status: not_affected` and the basis, and states that confirmation is required.

## Known failure modes
* **Reachable is function-level, not precondition-level.** cookiecutter's Jinja2 CVE-2025-27516 (`do_attr`) is reported reachable, but the advisory only affects `SandboxedEnvironment` and cookiecutter uses a plain `Environment`; the product does not read advisory preconditions.
* **Dynamic dispatch beyond the modelled patterns** (getattr-by-name visitors such as Jinja2's compiler `visit_*`, plugin discovery, entry-point groups) is not followed; such cases surface as unknown, or occasionally as "no path found" (see `CVE-2024-56201`, `CodeGenerator.visit_FromImport`, not resolvable statically). **"No path found" is never "not exploitable".**
* The vulnerable function is *inferred* from the fix commit; a fix may touch code that is not the vulnerable sink. About half of the advisories here (28 of 59) have no usable Python fix diff and are unknown.
* Entry points are the declared console scripts and public entry functions; plugin or framework hooks are not discovered.
* Reachability is not exploitability (configuration and attacker control are out of scope).
* Smoke checks are shallow (the app starts and exercises its dependency paths), not the app's test suite. The checks are executed on Python 3.11; PyYAML 5.3.1 has no wheel there, so a baseline for the PyYAML apps cannot be installed (reported as such).
* No held-out evaluation: the resolver's later features were driven by cookiecutter and HTTPie failures, so the numbers are descriptive, not a generalization estimate.
