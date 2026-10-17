# Which of these 25 vulnerabilities can actually be reached? A call graph in FalkorDB, a safe fix, and a fix that breaks the app

*Graph Hacks: Context for AI Agents, WeMakeDevs x FalkorDB*

## The problem

Software composition scanners match package names and versions. HTTPie 2.6.0 on the dependency versions an unrefreshed lock would pin produces **25 advisories**. The same scanner output arrives for every app and says nothing about whether *your* code can reach the vulnerable function. Vendors market "reachability" as a premium feature; the open alternatives mostly stop at "this package is imported".

I wanted the agent to answer three questions with evidence: **which alerts are reachable, what is the smallest safe fix, and does that fix still run?**

## Why a graph

Reachability is a path query across package boundaries:

```
entry point -CALLS-> ... -CALLS-> function in requests -CALLS-> the function the advisory's fix commit changed
```

In FalkorDB that is one `shortestPath((e:Function {entry:true})-[:CALLS*..25]->(v:Function {qname:$q}))` over about seven thousand functions in the app and eleven pinned packages. It returns the path, and the path is the explanation. The same graph holds the other relationships the answer needs:

* `EXTENDS` edges answer "does this loader class inherit the vulnerable constructor?";
* `DEPENDS_ON {spec}` edges hold every dependent's version constraint, so an upgrade plan is a graph query that gets re-run after an upgrade changes the constraints;
* `Decision` nodes in a shared graph let one app's verdict be recalled when the same advisory shows up in another.

## The hard part: a call graph that does not go blind

A plain call graph reports "no path" for a vulnerable PyYAML app, because `yaml.load(stream, Loader=FullLoader)` instantiates a class that is only *passed in*. So the resolver is call-site sensitive: class-valued parameters, `functools.partial` bindings (`yaml_load = functools.partial(yaml.load, Loader=Loader)`), handlers registered on classes (`FullConstructor.add_multi_constructor(...)`), handler tables (Jinja2's `FILTERS`), mixin `super()` through a subclass's MRO. Edges go caller -> target, so one call site passing `SafeLoader` never inherits another site's `FullLoader`.

The proof is a pair of apps with the same CRITICAL CVE (CVE-2020-14343, PyYAML 5.3.1): pre-commit gets **no path found**, a tiny app using `FullLoader` gets **reachable in two hops**. That positive control is a unit test, because an analysis that cannot say "reachable" for the vulnerable case cannot be trusted for the safe one.

## The vulnerable function is an inference, and we say so

OSV tells you the affected version range and the fixed version. It does not tell you the function. The agent takes the functions the **fix commit** changed (for PyYAML, which fixed the problem by moving handler registrations, it reads the removed registration lines). Where there is no Python fix diff (a data file, a shell template), the verdict is **unknown**, not "safe".

## Three verdicts, never "safe"

*Reachable*, *no path found within the analyzed scope*, *unknown*. When I read the output by hand I found `requests.HTTPAdapter.send` classified "no path found" even though every request goes through it: the adapter is chosen dynamically (`adapter = self.get_adapter(url)`). The fix was structural, not cosmetic: unresolved dynamic call sites now produce `MAYBE_CALLS` edges to same-package and direct-dependency candidates, and a path through them yields **unknown, possible path** instead of a false "no path". The case, and seven others, are in `docs/eval/ground-truth.md`.

## Acting, and checking the act

The planner picks, per package, the lowest installable version that clears the reachable findings, satisfies every dependent's constraint, and whose advisories are re-queried from OSV. Then it installs the proposal into a throw-away virtualenv and runs the app's entry points. Result on HTTPie: `requests 2.26.0 -> 2.32.4` clears two reachable CVEs and the app still starts and builds requests. `urllib3 -> 2.5.0` would clear a third, and **breaks HTTPie** (`ImportError: cannot import name 'DEFAULT_CIPHERS'`), so it is reported as "do not pin yet". The smoke checks are labelled for what they are: not the app's full test suite, and separate from the "this fixes the CVE" claim (which comes from the advisory's fixed range).

## Keeping the LLM honest

All analysis is deterministic Cypher. An optional LLM pass (Claude Haiku 4.5) re-reads the answer and attaches a supported / weak / unsupported verdict per step and action, but the server independently drops any claim whose cited paths, CVE ids or commit ids do not appear in what FalkorDB returned.

## Lessons

1. **Positive controls first.** The resolver first said "no path" for the vulnerable app; only a known-vulnerable control exposed it.
2. **Read your own output.** The most important bugs (hunk headers naming the wrong function, the `HTTPAdapter.send` false negative) were found by checking verdicts against source, not by tests.
3. **Refuse to overclaim.** "No path found" is a static-analysis result; it needs a different color than "safe".
4. **Run the fix.** The fix that clears the most advisories broke the app.

## What next

Runtime evidence (coverage traces) to turn "possible path" into a yes or no, more ecosystems through tree-sitter, SBOM and VEX import/export, and ownership routing so the owner of the code on the path is paged.
