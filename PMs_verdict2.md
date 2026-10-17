As product manager, I would give Claude Code a specific product outcome, measurable acceptance criteria, implementation priorities, and explicit constraints—not tell it to “make better use of FalkorDB.”

One technical distinction matters: FalkorDB's sparse-matrix representation and GraphBLAS execution are internal database capabilities. You generally exploit them through FalkorDB's graph queries and supported graph algorithms; you do not need to implement sparse-matrix operations yourself.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



Our product objective should be:

> Given a set of vulnerable dependencies, use graph reachability to determine which findings have evidence-backed paths through the application, recommend the smallest defensible remediation plan, and recompute the graph evidence to demonstrate the result.

This is the feature I would prioritize for Blast Radius. It makes the graph drive the decision itself, satisfying the hackathon's requirement that FalkorDB be central to the product.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.wemakedevs.org\&sz=32)

WeMakeDevs

+1



## Give Claude Code this product brief

# Product Requirements: Blast Radius — Reachability-to-Repair

## 1. Your role and the product goal

You are the senior engineer implementing this product. I am the product manager.

The existing Blast Radius application already has repository ingestion, a FalkorDB knowledge graph, stack-trace analysis, dependency traversal, git history, ownership inference, incident memory, a claim-verification layer, a UI and an MCP server.

**Do not rewrite the existing application. Reuse its working infrastructure and implement one exceptional, end-to-end new capability.**

The product is evolving from reactive incident investigation into graph-native vulnerability reachability and remediation planning.

The main user question is:

> Of the vulnerabilities in my dependencies, which have a demonstrated path from my application's entry points to vulnerable code, and what is the smallest defensible set of dependency upgrades that addresses those findings?

The graph must influence the findings, investigation sequence and selected remediation. It must not merely generate a diagram or supply context to an LLM.

## 2. Begin by inspecting the actual repository

Before editing code:

1. Read the project's agent instructions, README, architecture, graph schema, query implementation, security guard, test suite and frontend components.
2. Run the existing tests and identify the actual startup, ingestion and demo commands.
3. Map which existing nodes and edges can be reused for application functions, calls, external packages, versions, commits and owners.
4. Identify the shortest route to demonstrating a complete vulnerability investigation using the current codebase.
5. Document a concise implementation plan and the biggest technical risks in `docs/SECURITY_PIVOT.md`.

Then proceed with implementation without waiting for further approval. Do not spend hours writing a new architecture document or replacing working components.

## 3. The primary user workflow

The user selects a supported Python repository and starts a vulnerability investigation.

The application should:

1. Discover or load a curated set of verified vulnerability advisories and dependency versions.
2. identify vulnerable dependencies using confirmed package/version information.
3. Start from known application entry points and query the graph for paths to affected code.
4. Distinguish function-level reachability from package-level dependency exposure.
5. Rank findings using graph evidence, vulnerability severity, affected-service importance and analysis confidence.
6. Investigate candidate fixed versions and generate a remediation plan.
7. Simulate the proposed upgrades using graph-backed queries, without mutating the baseline graph.
8. Show which findings and exposure paths are resolved by the proposed upgrades, which remain unresolved, and why.
9. Produce an auditable report with evidence paths, supporting advisory records and a proposed dependency diff.

Preserve the existing incident-investigation functionality as a secondary mode.

## 4. Make FalkorDB central to the decision

Extend the current graph model only where necessary.

Reuse existing `Repo`, `Service`, `File`, `Function`, `Package`, `Commit` and `Person` nodes wherever possible.

Add or extend the following concepts:

- `EntryPoint`: an application route or other known entry into the program.
- `PackageVersion`: a specific installed dependency version.
- `Vulnerability`: an advisory with affected-version and fixed-version information.
- `VulnerableFunction`: affected library code, only when supported by evidence.
- `UpgradeCandidate`: a proposed target version for a dependency.
- `RemediationScenario`: a proposed upgrade set and its evaluated outcome.

Represent relevant relationships, such as application calls, package dependencies, installed versions, vulnerable versions, fixed versions, entry points and ownership.

Do not create a second, disconnected data model if the current schema can be extended cleanly.

### Required graph computations

A. **Reachability:** Execute bounded, evidence-returning graph traversals from known entry points through application and dependency relationships to affected code.

B. **Impact analysis:** Determine which services and application components are exposed through discovered paths. Use supported graph algorithms where they improve ranking or investigation decisions.

C. **Critical dependency analysis:** Identify dependencies that lie on multiple relevant paths or connect several exposed services. Where centrality or other graph algorithms are used, show how the result affects prioritization.

D. **Counterfactual remediation:** Evaluate a proposed dependency upgrade and recalculate the relevant reachable findings. Do not alter the baseline graph. Use an isolated scenario graph or a verified counterfactual query approach compatible with the installed FalkorDB version.

E. **Evidence verification:** Every reported path must correspond to relationships returned by FalkorDB. Every claimed fix must be supported by version/advisory evidence and the scenario evaluation.

F. **Adaptive investigation:** The agent must choose its next query based on earlier findings. For example, an incomplete function-level path should trigger a targeted dependency-resolution investigation, while a reachable vulnerability should trigger fixed-version discovery and remediation evaluation.

Do not run every query in a fixed sequence and use the LLM merely to summarize the results.

Do not implement your own sparse-matrix engine. Use FalkorDB's supported Cypher queries and graph algorithms. Verify algorithm names and query syntax against the installed version.

## 5. The remediation planner

This is the key product differentiator.

For each vulnerable dependency, identify candidate versions supported by advisory data. Where appropriate, evaluate combinations of upgrades.

Prioritize plans based on:

- The number and importance of evidence-backed reachable findings addressed.
- The number of exposed services and paths reduced.
- Dependency compatibility and version constraints.
- The magnitude of version changes and available test evidence.
- Unresolved vulnerabilities after the proposed upgrades.

Implement a transparent, deterministic ranking strategy. A greedy planner is acceptable for the initial version; do not build an unnecessarily sophisticated optimizer.

Show a score breakdown rather than presenting an arbitrary risk score as a probability.

The resulting plan should explain:

- Which packages should be upgraded and to which versions.
- Which findings each upgrade addresses.
- Which graph paths disappear in the proposed scenario.
- Which findings remain reachable or uncertain.
- Why this plan is preferred over at least one alternative.

If a version's fix status cannot be verified, do not recommend it as a confirmed fix.

Generate a proposed dependency-file diff and run available relevant checks when feasible. Never apply a patch or execute a rollback automatically.

## 6. Correctness rules

The product must use three distinct outcomes:

- **Reachable:** a supported path from a known entry point to the identified vulnerable code exists.
- **No path found within analyzed scope:** the analysis found no such path in the modeled graph.
- **Unknown:** incomplete call resolution, missing source, uncertain advisory mapping or insufficient evidence prevents a conclusion.

Do not equate “no path found” with “not exploitable.”

A path reaching an installed package does not prove that a vulnerable function inside that package is executed. Label such findings as package-level exposure unless function-level evidence exists.

Do not fabricate function relationships, advisories, fixed versions, test results or measured improvements.

Use public, permitted data. Clearly label curated examples and synthetic fixtures. Preserve the existing read-only Cypher guard, query limits, timeouts and path-verification mechanisms.

## 7. UI: demonstrate the decision, not just the graph

Add a focused Reachability-to-Repair view using the existing design system and graph visualization components.

The main screen should show:

1. Dependency and vulnerability counts.
2. Function-level reachable findings, package-level exposures and uncertain findings separately.
3. A highlighted application-entry-to-vulnerable-code path for a selected finding.
4. The relevant advisory, installed version and evidence for the fixed version.
5. The recommended upgrade plan and the graph evidence supporting its ranking.
6. A before/after view of reachable findings and paths under the proposed remediation.
7. The actual Cypher queries, latency and verification status for the key computations.

A judge should understand the value in 30–60 seconds, without reading the README.

Do not create a new frontend framework or rebuild the UI from scratch. Reuse existing components and recorded-replay infrastructure where possible.

## 8. Benchmark the product against a baseline

Create a reproducible evaluation using a small set of real, publicly documented advisories and repository cases.

Compare the graph-based approach against a simple baseline that flags vulnerable installed packages without code-level reachability analysis.

Record:

- Installed vulnerable package matches.
- Findings with verified function-level paths.
- Findings with only package-level exposure.
- Unknown or unresolved findings.
- Reachable findings remaining after the proposed remediation.
- Whether the correct known fix is identified.
- Query latency and total investigation latency.

Where ground-truth labels exist, include precision and recall. If they do not, disclose the limits of the evaluation.

Do not claim a reduction in false positives unless the benchmark establishes it. Do not compare results from different datasets or use the evaluation cases to make unsupported performance claims.

## 9. Acceptance criteria

The feature is complete only when the following are demonstrated:

1. A verified advisory and installed version produce the correct vulnerability finding.
2. A known entry point produces a real graph path to an identified vulnerable function for at least one working example.
3. A package-only match is not incorrectly presented as proof of function-level reachability.
4. The agent's subsequent investigation depends on the previous graph result.
5. A verified upgrade candidate produces a counterfactual evaluation without corrupting the baseline graph.
6. The recommended plan explains which reachable findings it resolves and which remain.
7. A graph computation materially changes the finding ranking or remediation decision compared with the naive baseline on at least one documented case.
8. The UI displays the actual path, query evidence and proposed remediation.
9. Automated tests cover the principal positive, negative, unknown and counterfactual cases.
10. Existing incident-investigation tests continue to pass.
11. Documentation explains the graph data model, important Cypher queries, algorithms, limitations, benchmark and reproducible demo procedure.

## 10. Priorities and stop conditions

The deadline is October 18, 2026, at 11:59 PM IST. Optimize for a working, demonstrable vertical slice rather than maximum feature count.

**P0 — Must work:** one complete, verified vulnerability path, one defensible upgrade recommendation, graph-backed counterfactual evaluation and a clear UI demonstration.

**P1 — Should work:** several advisories, graph-driven ranking, an adaptive investigation loop and a reproducible baseline benchmark.

**P2 — Only if time remains:** broader package support, more advanced optimization, elaborate visualizations or additional agent coordination.

Within the first hour, determine whether the existing ingestion and available advisory data can support a credible end-to-end example. If cross-package function resolution proves unreliable, narrow the demonstrated claim rather than inventing call edges. Keep an explicitly labeled package-level fallback.

Freeze new features by 6:00 PM IST. Reserve the remaining time for regression testing, deployment or local setup verification, a short demo video, README updates and submission.

## 11. How I will judge the implementation

I will evaluate your work against five questions:

1. Does FalkorDB do work that materially changes the answer?
2. Can the user inspect the evidence behind each decision?
3. Does the remediation planner make a non-obvious, useful choice?
4. Is there reproducible evidence that the graph approach improves on a naive baseline?
5. Can a judge run the demo and understand the contribution within two and a half minutes?

Implement the smallest solution that convincingly answers all five.

At completion, report what is implemented, which tests ran and passed, the actual benchmark results, remaining limitations, and exact demo commands. Do not mark a requirement complete merely because code has been written.

## How to manage Claude Code while it works

Don't let it optimize for lines of code or number of features. Manage it against three checkpoints.

### Checkpoint 1

First hour

Prove feasibility.

Ask it to demonstrate that one selected vulnerability can be represented accurately and traced through the existing graph. If that fails, narrow the scope immediately.

### Checkpoint 2

Middle of build

Prove the graph changes the decision.

Ask it to show the same case processed by the naive package-matching baseline and the graph-based workflow. If both produce the same result, adding more graph visualizations will not fix the product.

### Checkpoint 3

Before 6 PM IST

Demand the complete user journey.

Start with an advisory, inspect the path, examine the proposed upgrade, recompute the affected paths, and inspect the benchmark. Then stop adding features and prepare the submission.

The key PM principle is that the feature is not “vulnerability analysis using FalkorDB.” The feature is “a remediation decision that the graph can justify and reevaluate.” That framing gives Claude Code a concrete outcome to build toward while preserving the existing Blast Radius engine.