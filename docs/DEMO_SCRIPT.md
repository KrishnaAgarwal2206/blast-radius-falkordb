# Blast Radius — demo video script (2:30)

Record at 1440×860, browser at `http://localhost:8000` (or the live URL). Before recording: `python scripts/reset_memory.py` so memory starts clean, and have the stack trace ready (the first scenario chip fills it). Use **deterministic mode** for takes you may repeat; do the final take with **LLM agent** ticked (≈ 3¢).

| Time | On screen | Say |
|---|---|---|
| 0:00–0:12 | Hero card, dim service graph behind it | "It's 2 AM. Metrics stopped exporting, the pager is going off, and the question is always the same: what's broken, what changed, and who do I wake up?" |
| 0:12–0:25 | Click the **2 AM: metrics stopped exporting** chip (trace fills the box) | "I paste the stack trace. Blast Radius is an agent, but it doesn't guess — everything it knows comes from a FalkorDB graph of the codebase, its git history and its owners." |
| 0:25–0:55 | Run starts; nodes bloom, path hops light up amber one by one; Under-the-hood tab streaming Cypher with ms chips; totals bar counting | "Watch the graph: each frame of the trace is mapped to a Function node, then it walks reverse dependencies — 14 services depend on this code. On the right is the actual Cypher it's running against FalkorDB, with server-side latency. That's about thirty queries and a few milliseconds." |
| 0:55–1:25 | Answer tab; click the **cause** claim → camera zooms on `66a7c08f —MODIFIED→ measurement_consumer.py` | "Likely cause: a commit that touched exactly this function's file seventeen days ago. Click any claim and you see the exact path that proves it. A claim without a path is dropped — the agent can't invent a node." Click a **page** claim: "Who to page comes from ownership inferred from real commits — OpenTelemetry's CODEOWNERS is one catch-all team, so the graph does better than the file." |
| 1:25–1:45 | Lens toggle: **PageRank**, **Blast depth**, **Community**; open **Schema** | "These lenses are FalkorDB's native algorithms — PageRank, label propagation — recoloring the same graph. And this is the schema, read live from the database." |
| 1:45–2:15 | Memory timeline: shows the recorded incident; stop/restart FalkorDB container (cut), then investigate `measurement_consumer.py` | "Every investigation is written back as an Incident. After a restart, a related query recalls it — with the shared files and the commit that caused it. That's the memory track: the graph *is* the memory." |
| 2:15–2:30 | Architecture slide (README mermaid) | "Deterministic FalkorDB tools, a guarded Cypher escape hatch, an MCP server for Claude Desktop, and an LLM that only routes and narrates. Blast Radius: what breaks, what changed, who to page — with the path to prove it." |

## Shot checklist
- [ ] Reset memory, reload page (hero visible)
- [ ] Tick **LLM agent** only on the final take; cost shows in the Answer meta line
- [ ] After the run, press `1`–`4` for lenses
- [ ] Show `docker ps` / FalkorDB Browser (:3000) for 3 seconds as proof it's real
- [ ] Fallback if live run fails: `http://localhost:8000/?replay=scenario3`
