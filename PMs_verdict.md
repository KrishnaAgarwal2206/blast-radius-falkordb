# My decision: pivot, but not to the vulnerability scanner described in your proposal

Your analysis makes a strong case for moving beyond v1. However, after independently checking the current ecosystem, I found one important problem with its recommendation.

Vulnerability reachability is not an uncontested niche. OWASP's [VulnReach](https://github.com/OWASP/VulnReach?utm_source=chatgpt.com) already targets the question of which vulnerabilities are reachable in an application. Its project documentation describes Python reachability using AST analysis, route detection, taint analysis and runtime evidence, along with evidence chains and remediation guidance. Google’s OSV-Scanner also supports call analysis for supported languages.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



That doesn't make your idea bad. It means a product whose headline is simply “we use a graph to tell you which CVEs are exploitable” would have a much weaker originality argument than your memo assumes.

The hackathon's official rule is particularly relevant: FalkorDB must do central work, and the product must materially lose its capability if the graph database is removed. A graph visualization layered over an otherwise conventional scanner is insufficient.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.wemakedevs.org\&sz=32)

WeMakeDevs

+1



## 1. The product I would actually submit

[What Is External Attack Surface Management?](https://images.openai.com/static-rsc-4/4AGHKLZuqIGheKvZdGWqOEu7nc2zhhE-AhXibmBGnWczpoBHhbG-_wX7LidNjNQofkQ8DfpWvSxEIiKWfYAmoLSVsDmtyOmEKTVor3s_4G32RKLRDEaPoHEcg-fytNFDqlzBU-3serpPBhWCyO8fG4pD9yCWAnesF8_QE7I0ADk?purpose=inline)

[puppygraph.com](https://www.puppygraph.com/blog/external-attack-surface-management?utm_source=chatgpt.com)

# Blast Radius: Reachability-to-Repair

A graph-native security agent that investigates exploit paths and plans the smallest defensible remediation—not another CVE dashboard.

The central question becomes:

“Given these vulnerability alerts, which ones have a demonstrable path from an application entry point to vulnerable code, and what is the lowest-risk set of fixes?”

That is a stronger proposition than reporting which installed packages have known vulnerabilities.

### The four capabilities that make it distinctive

1\. Evidence-backed exploit-path investigation

Trace from a web route or other application entry point through the application's call graph, imports and dependency relationships to a known vulnerable function.

Every conclusion must show the actual path. Where the vulnerable function cannot be resolved reliably, report the finding as uncertain rather than inventing a path.

2\. Graph-driven remediation planning

Compare candidate package upgrades against the confirmed findings they resolve. Prefer a small set of suitable upgrades that addresses multiple findings without unnecessarily disturbing unrelated dependencies.

The graph identifies the relationships and exposures; a deterministic planner ranks the candidate changes. Do not call this a minimum cut unless you actually formulate and solve a graph-cut problem.

3\. Verified patch proposal

Draft an actual dependency-version change, show which findings it addresses, and run available checks against the proposed change. Display test results separately from the claim that the vulnerability is fixed.

GitHub Dependabot already supports grouping security updates, so batching updates alone isn't a compelling differentiator.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.github.com\&sz=32)

GitHub Docs

+1



4\. Persistent security decisions with evidence

Store previous investigations, accepted fixes, relevant dependency paths and the rationale for each decision in FalkorDB.

A later investigation can retrieve those episodes and explain why it is reusing or rejecting an earlier conclusion.

This differentiates your submission from both a basic code graph and a standard vulnerability scanner. It also creates a credible role for the existing ownership and incident-history engine.

## 2. What the graph must contain

I would extend the current graph with only the new elements needed for this workflow.

| New graph element    | Purpose                                                      |
| -------------------- | ------------------------------------------------------------ |
| `EntryPoint`         | A route, command handler or other externally reachable entry |
| `Vulnerability`      | CVE or advisory, affected version range and fixed version    |
| `InstalledVersion`   | The actual dependency version resolved for the project       |
| `VulnerableFunction` | The affected function, but only where verified               |
| `UpgradeCandidate`   | A proposed safe version and the findings it resolves         |
| `Test`               | Relevant checks and their observed results                   |

Useful relationships include `REACHES`, `DEPENDS_ON`, `AFFECTED_BY`, `FIXED_IN`, `OWNED_BY` and `VALIDATED_BY`.

The important query is no longer just “What depends on this package?” It becomes:

> Find the supported paths from application entry points to vulnerable functions, identify the upgrade candidates that resolve those findings, and show the evidence behind the chosen remediation plan.

That gives FalkorDB a direct role in finding the paths and determining the options considered by the agent.

One technical caveat: the OSV schema provides affected package information, version ranges and fixed-version events, but this doesn't automatically identify a vulnerable function. That mapping has to come from trustworthy advisory details, source analysis and verification.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://ossf.github.io\&sz=32)

Open Source Vulnerability schema

+1



## 3. The critical three-hour go/no-go test

I agree with the time-boxed pivot in your memo. I would make the acceptance criteria stricter, because the biggest risk is building something that looks impressive but cannot prove its core claim.

Run a prototype against two real Python applications and three manually verified advisories.

## Pivot gate

Advisory and version correctness

Confirm affected and fixed versions from authoritative advisory records.

Vulnerable-function mapping

Identify the actual vulnerable function or explicitly fall back to a weaker reachability claim.

End-to-end graph path

Show at least two credible paths from application code to vulnerable dependency code.

Actionable upgrade

Generate a candidate version change that resolves a verified finding.

Graph-dependent decision

Demonstrate that graph reachability changes the finding assessment or the selected remediation.

Gate status: 0/5 criteria checked

Do not treat checked boxes as proof until the corresponding test passes. Decide by hour three whether the available data and call resolution support the pivot.

Why the gate matters: Python imports, dynamic dispatch, optional dependencies and indirect calls can make cross-package reachability incomplete. If the function mapping fails, simply tracing to a package name would weaken the core claim.

Use three possible verdicts from the start:

- Reachable: a supported path to the identified vulnerable function was established.
- No path found within analyzed scope: no path was discovered by the implemented analysis.
- Unknown: evidence or call resolution is insufficient.

Never equate “no path found” with “not exploitable.”

## 4. How I would use the remaining time

You have approximately 26 hours between the current time and the October 18, 11:59 PM IST deadline. The original submission checklist also includes deployment or local setup instructions, a public repository, a working demo video, and documented graph queries.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.wemakedevs.org\&sz=32)

WeMakeDevs

+1



| Phase          | Focus                                                          | Exit criterion              |
| -------------- | -------------------------------------------------------------- | --------------------------- |
| Hours 0–3      | Verify advisories, apps and function mapping                   | Go/no-go decision           |
| Hours 3–9      | Add vulnerability nodes, version data and reachability queries | Working evidence paths      |
| Hours 9–14     | Implement upgrade candidate generation and remediation ranking | One end-to-end proposed fix |
| Hours 14–18    | Add persistent decisions and measurable baseline evaluation    | Reproducible results        |
| Remaining time | Polish the core graph view, record demo, deploy and submit     | Submission complete         |

The current `git blame`, ownership and incident investigation should be reused rather than rebuilt. If the pivot fails its gate, I would fall back to a more ambitious pre-merge change-risk workflow in Blast Radius, including before/after graph comparison and an actual held-out benchmark. I would not start the cloud-attack-path alternative with this deadline.

## 5. The judging standard I would hold you to

Before calling this a winning submission, I would want to see four things:

1. A non-obvious discovery: a real alert that looks severe from package metadata alone but receives a different, evidence-backed assessment after graph investigation.
2. A decision changed by the graph: not merely a graph path displayed after the agent has already chosen its answer.
3. A real action: an upgrade or patch proposal with relevant checks, not just generated recommendations.
4. Measured improvement: a baseline comparison on held-out examples, with actual counts, false positives and limitations disclosed.

The demo should show one complete case rather than 400 theoretical alerts. If the graph demonstrates a path that a naïve package-name match misses, and the agent then produces a defensible fix, that is a credible judging moment.

## Final verdict

Pivot away from v1 as a standalone incident-triage product. Do not pursue generic CVE reachability as the final differentiator.

Pursue Blast Radius: Reachability-to-Repair, where graph-backed exploit-path evidence drives a risk-aware remediation plan. Keep the existing engine as your foundation, and apply the three-hour gate before committing the remaining time.

That has a stronger upside than simply polishing v1, but only if you demonstrate working, verified reachability and an actionable fix. Without those, a last-minute pivot is more likely to weaken an already functional submission than improve it.