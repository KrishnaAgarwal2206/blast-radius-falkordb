# Claude Code Prompt — "Blast Radius": Graph-Powered Incident Agent (FalkorDB Hackathon)

> Paste everything below into Claude Code, run from an empty project folder.

---

## 0. Mission and hard constraints

You are the lead engineer building **Blast Radius**, a submission for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB).

- Hackathon page (read it first, including the Rules, Resources and Schedule sub-pages): https://www.wemakedevs.org/hackathons/falkordb#challenge
  - Rules: https://www.wemakedevs.org/hackathons/falkordb/rules
  - Resources: https://www.wemakedevs.org/hackathons/falkordb/resources
- **Deadline: October 18, 2026, 11:59 PM IST.** Check the current time with `date` at the start of every phase, and plan backwards from the deadline. Hard feature freeze is **6 hours before the deadline**. After the freeze, only fixes, polish, docs, deploy and the demo are allowed.
- **Non-negotiable rules from the organizers:**
  - FalkorDB must be the primary graph database and central to the product.
  - The graph must *shape what the agent does*, not sit on the side.
  - All FalkorDB work must be new during the event.
  - A live deployment is preferred. If the product can't be deployed, it needs full local setup instructions plus a demo video.
  - The team must be able to explain every architectural decision, so record each decision in `docs/DECISIONS.md`.
- **Target tracks:**
  - Primary: Track 01, Agents That Act on Connected Data.
  - Secondary: Track 03, Company Brain (ownership and who-knows-what).
  - Tertiary: Track 02, Agent Memory (incidents persist across sessions).
  - Also produce a blog post for the side prize.

### One-line product
Paste a stack trace, or name a service, file or function. Blast Radius walks a FalkorDB graph of your codebase, ownership and change history, then does three things:
- tells you what breaks,
- tells you which recent change most likely caused it and who to page,
- recalls similar past incidents.

It shows **the exact graph path behind every claim**, live, while the agent runs.

---

## 1. Operating rules for you (the orchestrator)

1. Use **subagents** (the Agent/Task tool) for the research phases below. Run the independent ones **in parallel**. Each subagent writes its findings to a file under `docs/research/`. You then read those files and make the decisions.
2. Keep a living plan in `PLAN.md` with checkboxes, and update it as you go. Keep `docs/DECISIONS.md` as a short ADR log with three fields per entry: decision, alternatives considered, why.
3. Commit to git after every working milestone, with clear messages. Never leave `main` broken.
4. Build a **thin vertical slice first**: ingest, then graph, then one agent answer with a path, then a minimal UI. Only after the slice works end to end do you deepen any layer.
5. When something is ambiguous, choose the option that makes the **demo clearer** and the **graph more central**, and log the choice.
6. Don't fake results. Every number, path and claim in the UI must come from a real FalkorDB query.

---

## 2. Phase 1 — Parallel research (spawn 2 subagents at once)

### Subagent A: "FalkorDB Research & Docs"
Goal: become the team's FalkorDB expert and write `docs/research/falkordb.md`. Cover:
- Setup:
  - running locally (`docker run -p 6379:6379 -p 3000:3000 -it --rm falkordb/falkordb:latest`; verify the current command in the docs),
  - FalkorDB Browser,
  - hosted FalkorDB Cloud options suitable for a live demo deployment.
- Clients: the Python client (`falkordb` on PyPI) API covering connect, select_graph, query, params, and result parsing. Note the Node client too, in case the UI needs it.
- Cypher dialect specifics and any differences from Neo4j that will bite us:
  - indexes,
  - `MERGE` behaviour,
  - variable-length paths,
  - path returns,
  - parameters,
  - full-text and vector indexes.
- **Graph algorithms** available natively, with exact procedure names and signatures:
  - shortest path,
  - PageRank,
  - betweenness/centrality,
  - WCC/connected components,
  - community detection (CDLP or whatever exists),
  - BFS.
- **Multigraph / multi-tenant**: one graph per repo, how to list, create and delete graphs.
- Integrations, with pros and cons for *this* project:
  - FalkorDB's MCP server,
  - GraphRAG-SDK,
  - Graphiti (for incident memory),
  - LangChain/LlamaIndex integrations,
  - QueryWeaver.
- Performance notes: bulk loading (batched `UNWIND`), query latency, and how to measure and display it.
- Prior FalkorDB demos or official example repos (for example, any code-graph demo FalkorDB publishes). We must know these so we **differentiate from them, not duplicate them**.
- End with a "Cheat sheet" section: 15–25 copy-pasteable, *tested* snippets. Spin up FalkorDB in Docker and run every snippet to verify it.

### Subagent B: "Problem & Prior-Art Research + Architecture"
Goal: write `docs/research/problem.md` and a proposed `docs/ARCHITECTURE.md`. Cover:
- **Why this problem matters.** Look at incident-response pain:
  - MTTR,
  - on-call routing,
  - "who owns this?",
  - change-induced outages (the share of incidents caused by recent changes).
  - Find credible stats from sources such as the Google SRE book, DORA, and postmortem collections. Cite links.
- **Prior art.** What exists and where each falls short:
  - code intelligence (Sourcegraph, CodeQL, GitHub dependency graph),
  - service catalogs (Backstage, OpsLevel, Cortex),
  - AIOps / incident tools (PagerDuty, incident.io, Rootly),
  - code-graph RAG projects on GitHub, including any FalkorDB/Neo4j code-graph demos,
  - previous hackathon winners with code-graph or incident agents.
- Then produce:
  - a differentiation table showing what Blast Radius does that none of them combine,
  - a section on **how to do it**, covering the patterns that work,
  - a section on **how NOT to do it**:
    - an LLM writing free-form Cypher with no guardrails,
    - graph used only as a vector-store sidecar,
    - giant unreadable hairball visualizations,
    - fake data,
    - over-scoped ingestion of every language.
- **Demo target repo selection.** Recommend 1–2 real, public, medium-sized repos (ideally Python, with multiple services or packages, active git history, and a CODEOWNERS file or clear authorship). The demo must be impressive and must ingest in under 2 minutes. Also propose 3 realistic "incident scenarios" for that repo, such as a realistic stack trace or a "service X is down" prompt, each with a known correct answer we can test against.
- **Layered architecture** proposal (see Section 3). Refine it, don't rubber-stamp it.

### After both return
Read both files and reconcile any conflicts. Finalize `docs/ARCHITECTURE.md` and the first entries in `DECISIONS.md`. Then build.

---

## 3. Product definition and layered architecture (baseline; refine with research)

**Default stack** (change only with a logged reason):
- Backend: Python 3.11+, FastAPI.
- Database client: `falkordb` Python client.
- LLM: the Anthropic API with tool use, reading `ANTHROPIC_API_KEY` from `.env`.
- Frontend: Next.js or Vite + React + Tailwind, with a WebGL/force graph library (evaluate react-force-graph, Sigma.js, Cytoscape in the UI phase).
- Infrastructure: Docker Compose for local; FalkorDB Cloud plus a free-tier host for the live deployment.

Every layer below gets its own folder, its own tests, and a short README section.

### L1 — Ingestion layer (`ingest/`)
- **What it does:** clones a repo and extracts entities and relationships.
  - From Python `ast` (tree-sitter optional): modules, files, classes, functions, imports, calls.
  - From `git log`: commits, authors, files changed, timestamps, churn.
  - From CODEOWNERS or blame: ownership.
  - From the package manifests: third-party dependencies.
  - From directory or config heuristics: services and packages.
- **Deliverables:**
  - `blast ingest <repo_url|path>` CLI,
  - idempotent loading (re-running doesn't duplicate),
  - batched `UNWIND` writes,
  - one FalkorDB graph per repo (multigraph).
- **Acceptance criteria:**
  - The demo repo ingests in under 2 minutes.
  - Node and edge counts are printed.
  - Spot checks of 5 known call/import edges pass in tests.

### L2 — Graph model layer (`graph/`)
- **Nodes:**
  - `Repo`, `Service`, `Module`, `File`, `Class`, `Function`, `Package` (third-party), `Person`, `Commit`,
  - `Incident` (memory), `Team` (optional).
- **Edges:**
  - `CONTAINS`, `IMPORTS`, `CALLS`, `DEFINES`, `DEPENDS_ON`, `OWNS`, `AUTHORED`, `MODIFIED` (Commit→File/Function, with lines changed),
  - `PART_OF` (→Service), `AFFECTED` (Incident→node), `CAUSED_BY` (Incident→Commit), `RESOLVED_BY` (Incident→Person), `SIMILAR_TO` (Incident↔Incident).
- **Deliverables:**
  - `graph/schema.md` with a diagram,
  - index creation,
  - typed query functions (no raw Cypher strings scattered in the codebase).
- **Acceptance criteria:**
  - Schema doc matches the DB.
  - Indexes exist.
  - Every query function has a unit test against a fixture graph.

### L3 — Graph intelligence layer (`analysis/`)
Deterministic, LLM-free functions that use FalkorDB queries and native algorithms:
- `blast_radius(node, max_depth)`: reverse dependency/call traversal, returning impacted nodes with depth and path.
- `trace_stacktrace(text)`: parse frames, map them to Function/File nodes, and expand callers and callees.
- `suspect_changes(nodes, window)`: rank recent commits touching the impacted subgraph by recency × churn × centrality.
- `who_to_page(nodes)`: owners and recent authors, weighted.
- `critical_nodes()`: PageRank and betweenness, giving the "single points of failure."
- `explain_path(a, b)`: shortest path as human-readable hops.
- **Deliverables:**
  - each function returns a structured result **plus the Cypher it ran and its latency in ms**, which the UI will show.
- **Acceptance criteria:**
  - Results are correct on the 3 known incident scenarios.
  - p95 query latency is logged.

### L4 — Agent layer (`agent/`)
- **What it is:** an LLM agent whose tools *are* the L3 functions, plus:
  - `query_graph` (read-only, guarded Cypher: reject writes, enforce LIMIT, add a timeout),
  - `recall_incidents` (graph memory),
  - `record_incident` (writes Incident nodes and edges after each investigation).
- **MCP server:** also expose the tools via an MCP server (`agent/mcp_server.py`), so any MCP client (including Claude Desktop) can use Blast Radius. This targets the "tool selection through MCP" focus area.
- **Output contract:** every final answer is structured with these fields:
  - `summary`,
  - `impacted[]`,
  - `likely_cause` (with evidence path),
  - `page[]` (people + why),
  - `similar_incidents[]`,
  - `confidence`,
  - `evidence_paths[]`.
  - **Any claim without a graph path behind it is not allowed.**
- **Streaming:** every tool call, Cypher query, node touched, and partial thought is emitted as an event (SSE/WebSocket) so the UI can animate the run live.
- **Acceptance criteria:**
  - All 3 scenarios produce correct, path-backed answers.
  - The agent never hallucinates a node that doesn't exist (verify every returned ID against the DB).

### L5 — Memory layer (`memory/`) — Track 02 angle
- **What it does:**
  - Incidents are persisted in the graph, linked to the affected nodes, cause commit and resolver.
  - A new investigation first checks for structurally similar past incidents (overlap in the impacted subgraph). Add embedding similarity only if time allows.
  - Isolate data per repo/tenant using separate graphs.
- **Acceptance criterion:** run scenario 1, restart the server, run a related scenario, and the agent cites incident #1 with the shared nodes.

### L6 — API layer (`api/`)
- FastAPI endpoints:
  - `POST /repos` (ingest), `GET /repos`,
  - `POST /investigate` (streams events),
  - `GET /graph/{repo}/subgraph?...`, `GET /graph/{repo}/schema`, `GET /graph/{repo}/stats`,
  - `GET /incidents`.
- Also OpenAPI docs and CORS.
- **Acceptance criterion:** an httpx test suite covers every endpoint.

### L7 — UI layer (`web/`) — designed in Phase 4, after the prototype works
Minimum for the prototype:
- an input box,
- a streamed answer,
- a basic graph view of the impacted subgraph.

---

## 4. Phase 2 — Thin vertical slice (build it yourself, no subagents)

1. `docker compose up` brings up FalkorDB, the API and the web app.
2. Ingest the demo repo.
3. Run scenario 1 from the CLI and get a path-backed answer.
4. Show it in a bare-bones UI.

Commit this and tag it `v0-slice`. **Do not start polishing anything until this works.**

## 5. Phase 3 — Deepen layers to their acceptance criteria
Work through L1 to L6 until every acceptance criterion passes. Write tests as you go:
- `pytest` for the backend,
- Playwright for one end-to-end UI flow.

Write a `make test` target that runs everything.

## 6. Phase 4 — UI research subagent (start only once the prototype works)

Spawn **Subagent C: "Live Graph UI Research & Design"**. It should study:
- the current prototype,
- FalkorDB Browser,
- the best graph visualization and devtools UIs (for example, Neo4j Bloom, Linear-style polish, and observability tools like Honeycomb or Grafana traces).

It writes `docs/research/ui.md` with a concrete spec, then you implement it. The UI's purpose: **make FalkorDB's graph architecture and its use case visible live during a run.** Required elements:
- **Live traversal animation.** As the agent runs, the nodes and edges it touches light up hop by hop, in sync with the streamed events. Nodes are coloured by label and sized by PageRank.
- **"Under the hood" panel.** Every Cypher query the agent executes appears in real time with its latency in ms, row count and the tool that issued it. This is the FalkorDB showcase.
- **Schema view.** A small meta-graph of labels and relationship types with counts, showing the data model at a glance.
- **Evidence-linked answer.** Clicking any claim in the answer highlights its exact path in the graph.
- **Algorithm lens.** A toggle to recolour the graph by PageRank, communities or blast radius depth.
- **Memory timeline.** Past incidents, with a "similar to" link that pulls in their subgraph.
- **Repo switcher** showing multiple graphs in one FalkorDB instance (multigraph feature).
- **No hairballs.** Show the relevant subgraph only, with progressive expansion on click.
- **Visual quality.** Dark-mode-first and responsive. The first screen should explain the product in about 5 seconds, using a one-click "Run demo scenario" button.

## 7. Phase 5 — Hackathon-grade evaluation loop (repeat until it passes)

After each major iteration, spawn a **fresh "Judge" subagent** that has *not* seen your build context. Give it only:
- the hackathon page URL,
- the live URL or local run instructions,
- the README.

It must actually run the product, then score it 1–10 on each criterion below with specific evidence and a prioritized fix list. It writes the result to `docs/eval/round-N.md`.

| # | Criterion | Pass bar |
|---|---|---|
| 1 | FalkorDB is central: the graph clearly drives decisions, and multi-hop reasoning and algorithms are used | ≥ 9 |
| 2 | Correctness on the 3 known scenarios plus 2 new scenarios the judge invents | 5/5 correct |
| 3 | Explainability: every claim has a visible, clickable graph path | ≥ 9 |
| 4 | Live demo wow factor: the traversal animation and under-the-hood panel make the architecture obvious to a non-expert in under 90 seconds | ≥ 8 |
| 5 | Track fit for 01 (primary), plus credible 03 and 02 angles | ≥ 8 |
| 6 | Robustness: no crashes on bad input, a malformed stack trace, an unknown repo, or an API timeout; graceful errors | ≥ 8 |
| 7 | Performance: demo repo ingest under 2 minutes, investigation under 20 seconds, query latencies shown | ≥ 8 |
| 8 | Setup: a fresh clone runs with `docker compose up` plus one env var, following the README exactly | Works first try |
| 9 | Code quality: layered structure, tests passing, no secrets committed, clear README | ≥ 8 |
| 10 | Originality versus the prior art in `problem.md` | ≥ 8 |

**Loop rule:**
- If any criterion is below its pass bar, fix the top-priority issues, then spawn a *new* Judge (fresh context) and re-score.
- Repeat until every criterion passes.
- **Time override:** at the feature freeze (deadline − 6h), stop adding scope. Fix only criteria 2, 6 and 8, then move to Phase 6 regardless.

## 8. Phase 6 — Submission package (must be finished by deadline − 1h)

- **Live deployment.** FalkorDB Cloud (or a hosted container) plus the API and web app, with a working public URL. Pre-ingest the demo repo so judges never wait.
- **README.md** with:
  - pitch, GIF, architecture diagram (Mermaid), graph schema,
  - which tracks it targets and why,
  - how FalkorDB is used (with specific queries and algorithms),
  - setup steps, demo scenarios, tech stack,
  - limitations and next steps.
- **Demo video script**, `docs/DEMO_SCRIPT.md`, 2–3 minutes long:
  - Hook: "it's 2 AM, payments is down."
  - Paste the stack trace and watch the live traversal.
  - Show the answer with evidence paths.
  - Show the under-the-hood Cypher panel.
  - Show the memory recall.
  - Close on the architecture slide.
- **Blog post draft**, `docs/BLOG.md`, for the AirPods side prize:
  - the problem,
  - why a graph,
  - schema design choices,
  - one interesting Cypher/algorithm trick,
  - lessons learned,
  - what we'd build next.
- `docs/DECISIONS.md` complete enough that the team can explain every choice to the judges.
- A final fresh Judge pass on the *deployed* URL.

## 9. Final report to me

When you're done, tell me:
- the live URL,
- the final scores table,
- what's still weak,
- the exact steps I need to take myself: recording the video, submitting on the WeMakeDevs dashboard, and posting the blog.
