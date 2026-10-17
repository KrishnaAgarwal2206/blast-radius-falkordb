# Teaching an incident agent to show its work: building Blast Radius on FalkorDB

*Graph Hacks: Context for AI Agents — WeMakeDevs × FalkorDB*

## The problem

When production breaks, the first ten minutes go to three questions: **what else is broken, what changed, and who owns it?** Google's SRE book says roughly 70% of outages come from changes to a live system, yet the answer to "what changed near this stack frame, and who touched it?" lives in three different places — the code, the git log and somebody's head. Service catalogs know owners but not call graphs; code-intelligence tools know call graphs but not incidents; AIOps tools know incidents but not code.

## Why a graph

Each of those questions is a *traversal*, not a lookup:

```
stack frame ─→ Function ←CALLS─ Function ←IMPORTS─ File ←DEPENDS_ON─ Service     (what breaks)
Function ←MODIFIED─ Commit ←AUTHORED─ Person                                      (what changed, who)
Incident ─AFFECTED→ File ←AFFECTED─ Incident                                      (seen this before?)
```

In a relational store each hop is a join you have to remember to write. In FalkorDB the same question is one pattern, runs in about a millisecond, and — crucially for an agent — **returns the path**, which is the explanation. We wanted the agent's answer to be *checkable*: every claim carries a path id, the UI highlights that path, and the server drops any claim whose path the graph never returned.

## Schema decisions

* **Service vs Package.** A Service is an in-repo deployable (a directory with its own `pyproject.toml`); a Package is an external dependency. Mixing them makes "blast radius" ambiguous, so `DEPENDS_ON` is typed on both ends.
* **No Module node.** A Python module *is* a file; one fewer node type, less clutter on screen.
* **Evidence edges carry provenance.** `OWNS {source:'inferred', score}` is a recency-weighted share of non-bot commits, not a fact. `CALLS {confidence}` says how an edge was resolved. The UI never claims more than the edge says.
* **Incidents are real.** We derive them from fix/revert commits in the repo's own history and find `CAUSED_BY` with `git blame` on the removed lines (an SZZ-style heuristic). New investigations are written back as `Incident` nodes, so the graph is the agent's memory.

## One trick worth stealing: put the LLM *behind* the graph

The agent's tools are deterministic Cypher-backed functions (`blast_radius`, `suspect_changes`, `who_to_page`, …). The model chooses the order and writes the narrative; it cannot make up a node. For the escape hatch (`run_cypher`) we use `GRAPH.RO_QUERY`, strip string literals before keyword checks, force a `LIMIT`, and return the schema in the error message so the model self-corrects. Final answers are validated: any claim citing a path id the tools never produced is discarded (the UI even shows "N claim(s) dropped: no graph path"). In a live run, Claude Haiku 4.5 invented two such citations — the validator caught both.

The second trick is cheap and visible: a `contextvar`-scoped query tracker wraps the FalkorDB client, so every Cypher string and server-side `run_time_ms` streams to the UI's "under the hood" panel. Showing 30 queries in 15 ms is the best pitch for a graph database we could make.

## Algorithms in the loop

`algo.pageRank('Service','DEPENDS_ON')` ranks single points of failure (edges point dependent→dependency, so high rank = many things rely on it: `opentelemetry-api` tops the OpenTelemetry-Python graph). `algo.betweenness` finds the brokers (`opentelemetry-sdk`), and `algo.labelPropagation` colors communities. They run on 25 services in about a millisecond.

## Lessons learned

1. **FalkorDB gotchas:** `RO_QUERY` on a graph that doesn't exist errors; `shortestPath` only works in `WITH`/`RETURN`; the default 1 s query timeout kills algorithms on bigger graphs; operator precedence in `ENDS WITH '.' + $t` needs parentheses (we learned that from a type error).
2. **Real data beats fixtures.** Pointing the tool at `open-telemetry/opentelemetry-python` immediately exposed noise (release-bump commits as "suspects", a single catch-all CODEOWNERS), which made the product better than synthetic data would have.
3. **Make the stream the product.** Designing the SSE event schema first (tool_call, graph_query, subgraph, path, claim) made the CLI, API, UI, replay mode and tests all consumers of the same stream.
4. **Budget the LLM.** Haiku 4.5, prompt caching, compact tool results and a spend ledger kept a full agent run to about 2–3 cents; the deterministic pipeline is a zero-cost fallback.

## What's next

Tree-sitter for more languages, embedding rerank on top of the deterministic `SIMILAR_TO`, deploy-event and on-call-schedule nodes so "who to page" also knows who is awake, and per-commit graph snapshots with `GRAPH.COPY` to answer "what did the blast radius look like last week?".
