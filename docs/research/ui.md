# Blast Radius - Live Graph UI Spec (no-build, dark-first)

Stack: `web/index.html` + `web/app.js` (ES module, split into `<script type="module">` imports of sibling files) + `web/style.css`. CDN only:
- `force-graph@1.43.5` (canvas, d3-force; already in prototype). Chosen over cytoscape/sigma: native `linkDirectionalParticles`, per-frame `nodeCanvasObject`/`linkCanvasObject` hooks, `zoomToFit(ms,pad,filterFn)` for camera-fit, tiny, and no layout plugin needed. Sigma (WebGL) is only worth it past ~20k nodes; we cap visible nodes at ~400, so canvas is fine.
- Highlighting: ~60-line hand-rolled Cypher tokenizer (no lib; keeps bundle zero). Fonts: Inter + JetBrains Mono via Google Fonts (fallback system-ui / ui-monospace).

Design lessons taken (from FalkorDB Browser, Neo4j Bloom/Browser, Honeycomb/Grafana trace views):
- FalkorDB Browser / Neo4j Browser: query text + result graph side by side, schema meta-graph, double-click expand. Weakness: hairballs, no narrative. We keep the query visible but make it a *timeline*, not a console.
- Bloom: search-first, legend by label with color+icon, rule-based styling (our "lens"), "expand neighbours" capped.
- Honeycomb/Grafana traces: waterfall of spans with duration bars, click span -> detail. We mirror it: each Cypher query is a "span" row with an ms bar scaled to the slowest query; hover a row highlights the nodes it returned.

## 1. Layout

Desktop (>=1024px): CSS grid, `grid-template-columns: 340px minmax(0,1fr) 380px; rows: 52px 1fr 36px`.
```
[ top bar: logo | repo switcher | lens toggle | replay/live pill | totals bar (queries / total ms / p95) ]
[ LEFT: Investigate  | CENTER: graph canvas (+legend, +mini schema toggle) | RIGHT: tabs: Under the hood / Answer ]
[ bottom strip: memory timeline of incidents (collapsible, 36px collapsed, 160px open) ]
```
- LEFT: input (stack trace / service name), scenario chips, agent "thinking" feed (compact, last 6 lines), claims list lives in Answer tab.
- RIGHT tabs: **Answer** (streamed answer + claim cards) | **Under the hood** (Cypher spans). Auto-switch to Under the hood on `run_started`, to Answer on `run_finished`; user click pins the tab for the run.
- Mobile (<768px): graph is full-bleed on top (55vh); below is a bottom sheet with 4 tabs (Investigate | Answer | Cypher | Memory), sheet drag-handle snaps 25/60/90%. Top bar collapses to logo + repo + hamburger (lens, replay). Totals bar becomes a single line under top bar. Tap = hover (tooltip card pinned at bottom of graph, dismiss on tap-away).

### First-screen hero (empty state, before any run)
Graph canvas shows the *real* critical-service graph dimmed (from `/critical` + `/subgraph`), with an overlay card centered (max 560px):
- H1 (32px/600): "What breaks if this changes?"
- Sub (16px, dim): "Paste a stack trace or name a service. An agent walks a live FalkorDB graph of code, commits, owners and past incidents - and every claim links to the exact path."
- Primary button (accent, 48px): **Run demo scenario** (runs scenario 1 via `/api/replays/{name}` if `?replay` or API cold, else live `/api/investigate`).
- 3 scenario chips below (outline pills, icon + title + dim subtitle): e.g. "Blast radius of opentelemetry-api", "Who owns this crash? (paste trace)", "Seen this before? (similar incidents)". Chips fill the input and run on click. Hard-code in `SCENARIOS` const in app.js; each has `{id,label,sub,input,replay}`.
- Footer line of hero: live stat chips from `/stats`: "3,655 nodes - 9 labels - FalkorDB". Overlay fades out (300ms) on `run_started`; Esc / "x" brings it back via a "?" button.

## 2. Live traversal animation

Event -> visual mapping (single `Director` class with a FIFO queue; `ingest(ev)` pushes, `tick()` drains with rAF):
| SSE event | Visual | Duration |
|---|---|---|
| run_started | clear highlights, dim all existing nodes to 25% opacity, hero fades | 300ms |
| thinking | append to feed with typewriter (30 chars/frame cap), pulse "agent" dot | n/a (non-blocking) |
| tool_call | open a new span group in Under the hood, status "running" spinner | instant |
| graph_query | add query row (slide-in 150ms), ms bar grows 0->width (400ms ease-out), counters tick | 150-400ms |
| subgraph | merge nodes/edges (see below), nodes "pop in" (radius 0 -> r, easeOutBack, 350ms) with ring flash; stagger 25ms per node, max 600ms total | <=600ms |
| path | hop-by-hop animation (below) | 450ms/hop |
| claim | add claim card (fade+rise 200ms); no graph change until clicked | 200ms |
| error | red toast + red left border on the span; graph unchanged | instant |
| run_finished | stream answer, final camera `zoomToFit(600, 60, inPaths)`, totals bar final tick | 600ms |

**Hop-by-hop path animation** (`path{nodes[], rels[]}`): for i in 0..n-1: at `t0 + i*450ms` node i gets an expanding ring (radius r -> 2.4r, alpha 0.8 -> 0, 500ms, easeOutCubic) and fills with its label color at full saturation + 2px white stroke; edge i (between node i and i+1) is drawn progressively: custom `linkCanvasObject` draws a line from source to `lerp(source,target,p)` with p = easeInOutCubic over 400ms, width 3px, color `--path` (#FFB000) with a glow (`ctx.shadowBlur=12`), plus 3 `linkDirectionalParticles` (width 4, speed .012) on that link after it completes. Relationship type label drawn at link midpoint at zoom > 1.2 or when part of an active path. After the last hop, the path stays lit (width 3) while other paths drop to width 1.5 at 60% alpha ("settled"). Keep per-node state in a `Map<id,{born,flash,lit,settled}>` and per-link state similarly; `nodeCanvasObject` reads timestamps, so no tweening library; call `fg.d3ReheatSimulation()` never (avoid jitter - see section 8) - instead `fg.pauseAnimation` is NOT used; set `autoPauseRedraw(false)` while the queue is non-empty so the canvas redraws every frame, true when idle.

**Queue / catch-up policy** (never lag >2s): each queued item has `enqueuedAt`. Compute `lag = now - head.enqueuedAt`. Speed factor `k = clamp(1 + (lag-500)/1000, 1, 4)`; all durations divided by `k`. If lag > 2000ms, skip-to-final for non-path items (subgraph pops become instant, typewriter flushes) but keep path hops at min 120ms/hop so the signature moment survives. Replays use same code with `k=1` unless the user picks 2x/4x.

**Merging subgraph**: never `graphData(newObject)` (it resets layout). Maintain `nodes[]`, `links[]` arrays + `Map`s; push new items and call `fg.graphData({nodes,links})` with same object refs. New nodes spawn at the position of an already-present neighbour (+/-8px jitter) so they bloom outward instead of flying in from origin. Use `cooldownTicks(60)` and `d3AlphaDecay(0.04)`, `d3VelocityDecay(0.35)`. Camera: after each subgraph, `zoomToFit(500, 80, n => n.new)` only while no user pan/zoom happened in the last 4s (track `onZoom` events with `userMoved` flag, cleared on "Re-center" click).

**Node encoding**: color = label (palette sec. 9); shape = label (redundant cue, sec. 9); radius = `3 + 12 * sqrt(norm(score))` where score = `pagerank` if available (Service nodes from `/critical`), else `log(1+degree)` computed client-side from the loaded edges; min 3, max 15. Non-Service nodes default r=4-6. Seed/blast-source node gets a persistent dashed halo.

## 3. "Under the hood" panel

Each `tool_call` opens a **group** (card): header = tool name (mono, accent chip), args summary (truncated 60 chars), status dot (running/ok/error), group duration. Inside, one **query row** per `graph_query`:
```
[ms chip 12ms] [rows chip 37 rows]                [copy] [expand]
MATCH (s:Service {name:$k})<-[:DEPENDS_ON*1..3]-(d) RETURN ...
[=========-----] bar = ms / max(ms) across run
```
- Cypher: `<pre class="cy">` with tokens: keywords (MATCH, WHERE, RETURN, WITH, OPTIONAL, ORDER BY, LIMIT, CALL, YIELD, AS, IN, AND, OR, NOT, DISTINCT, UNWIND, CREATE, MERGE, SET, COUNT...) `--tok-kw` #C792EA; labels `:Name` `--tok-label` (use that label's node color); rel types in `[:TYPE]` `--tok-rel` #FFB000; params `$x` #F78C6C; strings #C3E88D; numbers #FF9CAC; functions (`\w+(`) #82AAFF; comments dim. Regex order: comment, string, param, `:\w+` label/rel, number, keyword, function. Collapsed to 2 lines (`-webkit-line-clamp:2`), click expands. Pretty-break before MATCH/WHERE/RETURN/WITH/ORDER/LIMIT for display only; copy button copies the raw cypher (`navigator.clipboard.writeText`, fallback textarea; button flips to "Copied" 1.2s).
- Latency chip colors: <20ms green, 20-100 amber, >100 red (always with number, never color only).
- Hover a query row: nodes returned by it (track `queryId` on nodes arriving in the next `subgraph`) get a halo. Click: filter graph to that set (toggle).
- Tool grouping: group collapse/expand; header shows "3 queries, 41ms".
- **Totals bar** (top bar, always visible): `Queries 14 | Total 212ms | p95 38ms | Nodes touched 186`. Update on each `graph_query` with number roll animation (150ms). p95 = sorted-array nearest-rank over run's `ms` list. A tiny sparkline (inline SVG, 14 bars) of per-query ms next to it. Label hint "FalkorDB time only; LLM time excluded" in tooltip, and show `run_finished.ms` + `cost_usd` right-aligned afterwards.

## 4. Schema meta-graph

Button "Schema" (top-bar toggle and left-pane link). Fetch `/api/graph/{g}/schema` -> `{labels:{Label:n}, patterns:[{a,type,b,n}]}`. Render in the same force-graph instance in "schema mode" (swap graphData, remember main one) or in a modal 640x420 with a second ForceGraph instance (preferred - no state loss). Nodes = labels, radius `6 + 14*sqrt(n/maxN)`, label text "Function 2,089"; edges = patterns (aggregate duplicate a/type/b), width `1 + 4*log(n)/log(maxN)`, curved (`linkCurvature` 0.2; self loops like Function-CALLS->Function use `linkCurvature` 0.6 + `linkDirectionalArrowLength`), edge label `CALLS 1,037` at midpoint. Click a label node -> "Show top nodes of this label" (calls `/subgraph` w/ top critical ids; for Service uses `/critical`). Run-time cue: labels/rels touched in the current run's queries glow (parse `:Label` and `[:TYPE]` out of cypher with the tokenizer) - this makes "FalkorDB is being traversed" visible on the schema.

## 5. Evidence-linked answer

- Answer text: claims rendered as inline superscript chips `[1]`; cards below: sentence, `path.sentence`, confidence if any, node-label breadcrumbs (colored dots). Claim -> `path_id` -> `paths[path_id]` map.
- Click claim (or `[n]` chip, or Enter on focus): set `activePath`; all else dims to 15% opacity; path nodes/edges redrawn with the section 2 look instantly (no hop animation unless Shift-click = replay hop animation); `zoomToFit(600, 90, n => pathSet.has(n.id))`; claim card `aria-pressed=true`; Esc clears and restores camera. URL hash `#claim=c2` is shareable.
- Hover node (desktop) / tap (mobile): tooltip card (not default canvas title): `label` color dot + badge, primary name, up to 6 props (key dim, value mono, truncated 48 chars, full on click), degree, pagerank (if known), "Expand (e)" button, "Open in path" if node is in any claim. Position near cursor with edge-avoidance; fixed bottom card on mobile. Implement with `onNodeHover` + absolutely positioned div, props from `/subgraph` response `props` (nodes from `/expand` have only `{id,label,key,name}`, so lazily fetch `/subgraph?ids=<id>` on first hover and cache).
- Edge hover: show `type` and endpoints.

## 6. Algorithm lens

Segmented control in top bar: **Label** (default) | **PageRank** | **Blast depth** | **Community**. Lens only changes node fill (and size for PageRank); animate with 400ms color lerp.
- PageRank: sequential ramp (`#2A3A5C` -> `#56B4E9` -> `#FFF3B0`), size by score. Data: `/critical` returns `{critical:[{uid,pagerank,betweenness}]}` top-15 only for scope Service. Nodes without score: grey `#3A4254`, r=3. Legend "scored: top 15 services (PageRank via FalkorDB algo.pageRank)".
- Blast depth: BFS hop distance from the seed/source node(s) over the **currently loaded** edges, computed client-side (dependents direction: follow edges as the agent's query did; default undirected BFS with edge-type filter DEPENDS_ON/CALLS/DEFINES/CONTAINS). Colors: 0 `#FF5A4A`, 1 `#FFB000`, 2 `#F0E442`, 3+ `#56B4E9`, unreached grey. No new endpoint needed. Legend shows counts per depth (the "blast radius" histogram - also render it as a mini bar chart in the Answer tab).
- Community: **needs data**. Without it, fall back to client-side label-propagation on loaded subgraph (30 lines, deterministic seed) and tag the legend "approx. (client-side)". Recommended small endpoints (P1):

`GET /api/graph/{g}/scores?scope=Service&ids=<optional comma list>` ->
```json
{"scope":"Service","algo":{"pagerank":"algo.pageRank","community":"algo.WCC"},
 "scores":{"Service:opentelemetry-api":{"pagerank":0.00414,"betweenness":0.0,"community":3,"degree":21}},
 "max":{"pagerank":0.00414,"degree":21},
 "queries":[{"cypher":"CALL algo.pageRank(...)","ms":41,"rows":25}]}
```
Return scores for ALL Service nodes (25) and, if `scope=Function`, top 200 by degree. Cache server-side (graph is static between ingests).

`GET /api/graph/{g}/blast?id=Service:opentelemetry-api&depth=3&limit=150` ->
```json
{"seed":"Service:opentelemetry-api",
 "nodes":[{"id":"Service:opentelemetry-sdk","label":"Service","depth":1}],
 "edges":[{"id":"...|DEPENDS_ON|...","source":"..","target":"..","type":"DEPENDS_ON"}],
 "queries":[{"cypher":"...","ms":9,"rows":42}]}
```
(Gives server-truth depth so the lens doesn't depend on what is loaded; also useful as "Show blast radius" button on any node's tooltip.)

## 7. Memory timeline + repo switcher

- Timeline strip (bottom): from `/api/incidents?graph=g` -> `[{id,title,ts,source,cause}]`. Horizontal scroll axis by `ts` (seconds epoch; convert `*1000`), each incident a dot (Incident color), height-jitter by index to avoid overlap, tick labels by month. Hover: title tooltip. Click: select -> side card with title, source, cause sha (short, mono), button **Pull into graph** (calls `/subgraph?ids=Incident:<id>,Commit:<cause>` + `/expand?id=Incident:<id>` and animates the "similar to" edges: SIMILAR_TO neighbours bloom in with the section 2 pop animation and dashed amber edges) and **Investigate this** (fills input). During a run, incidents whose ids appear in the nodes of `subgraph` events get a pulsing ring on the timeline: "memory recalled".
- Mobile: Memory tab = vertical list sorted desc, same actions.
- Repo switcher: select in top bar from `/api/repos` -> `[{graph,nodes}]` (label: `otel (3,655 nodes)`). On change: abort current SSE, clear graph, refetch stats/critical/incidents/schema, set `?g=` in URL, hero re-shows with that graph's critical subgraph. All fetches take `g` from a single `state.graph`.

## 8. No-hairball rules + progressive expansion

1. Hard cap 400 visible nodes, 800 links. Over cap -> evict least-recently-lit non-path leaf nodes first (fade-out 300ms) and show chip "+N hidden".
2. Default view shows only Service/Incident/Commit/Person-of-interest + path nodes; File/Class/Function appear only when part of a path or explicitly expanded. Filter chips per label in the legend (click toggles; shows count).
3. `/expand` returns <=60 neighbours; client shows first 12 per relationship type, then a synthetic cluster node "+N Function" (dashed ring) that on click loads next 12 (`limit` param up to 60; if more needed, add `offset` - recommended tiny API change: `offset:int=0`).
4. Expand triggers: double-click node, `e` key, tooltip button. Expansion animates children from parent position (spawn at parent). Each expand adds a query row to Under the hood (response includes `queries[]`) and updates totals bar.
5. Labels (text) drawn only when: zoom > 1.8, or node is in active path, or hovered, or r > 9 (top PageRank). Edge labels only on active path/hover.
6. Edges default alpha .25, width 1; curved parallel edges (`linkCurvature` by index among parallels); no arrowheads unless zoom > 1.5 or active.
7. Layout stability: pin dragged nodes (`fx,fy`), no reheat on merge, warm-start positions as in sec. 2; `d3Force('charge').strength(-60)`, `distanceMax(250)`, `d3Force('link').distance(l => 40)`; label-grouping force: weak `forceX/forceY` pulling by label to ring-sectors (strength .03) so Function clouds do not overlap Services.
8. Collapse button on any expanded node ("Collapse (c)") removes children it introduced and which have degree 1 within loaded set.

## 9. Accessibility, palette, type, states, replay

**Palette tokens** (dark-first; light theme optional P2 via `[data-theme=light]`):
```
--bg:#0A0D14; --surface:#111622; --surface-2:#171E2D; --line:#242C3F;
--fg:#E8ECF4; --dim:#98A2B8 (contrast 7.0 on bg); --accent:#FF6B4A; --accent-ink:#1A0A06;
--path:#FFB000; --ok:#3DDC97; --warn:#FFB000; --err:#FF5A6A; --focus:#7CC4FF;
```
Node labels - Okabe-Ito-derived, lightened for dark bg, each also has a distinct shape so color is never the sole cue (checked mentally against deuteranopia/protanopia/tritanopia: adjacent hues separated by luminance and shape):
| Label | Hex | Shape |
|---|---|---|
| Repo | #F0E442 | hexagon |
| Service | #56B4E9 | rounded square |
| File | #A3B1C6 | square (small) |
| Class | #CC79A7 | diamond |
| Function | #2FBF9A | circle |
| Package | #E69F00 | triangle |
| Person | #C4B5FD | circle with ring |
| Commit | #7C8CF8 | small pentagon... use circle with center dot |
| Incident | #FF5A4A | 5-point star |
(9 labels in graph; the stated "8" + Incident. Function and Commit are both circles but differ by hue-luminance (teal L~65 vs periwinkle L~62) and the center dot.) Path/active highlight uses amber `--path`, deliberately not a label color: Package orange #E69F00 is dimmed (drawn at 85% sat) only when a path is active.

**Typography**: Inter 14/1.45 body, 12px labels uppercase tracking .08em for section headings, JetBrains Mono 12/1.5 for Cypher, ids, ms. Hero H1 32/600 (24 on mobile). Tabular-nums on all counters (`font-variant-numeric: tabular-nums`).

**A11y**: all controls are real `<button>`s with visible 2px `--focus` outline; claims are `role=listbox` options navigable with arrows; canvas has `role="img"` + `aria-label` summarizing current view and an `aria-live="polite"` visually-hidden log that receives one sentence per event (e.g. "Query 3 returned 37 rows in 12 ms", "Path: A depends on B depends on C") - screen-reader equivalent of the graph; a "Table view" toggle lists visible nodes/edges as `<table>`. Honor `prefers-reduced-motion`: no ring pulses/particles, hops become instant highlight, camera jumps without easing. Min target 40px on mobile. Contrast >= 4.5:1 for all text; latency chips include text. Keyboard: `/` focus input, `Enter` run, `e` expand, `c` collapse, `Esc` clear selection, `1-4` lens, `r` replay, `?` shortcuts overlay.

**States**:
- Empty: hero (sec. 1). Empty panel text: "Run an investigation to see FalkorDB's queries stream here."
- Loading: skeleton shimmer on panels (CSS gradient 1.2s), graph shows spinner ring + "Connecting to FalkorDB..."; first-run cold API: 8s timeout then offer "Play recorded replay" automatically.
- Error: SSE `error` -> red span + toast with message and **Retry** + **Play replay** buttons; EventSource drop -> exponential backoff 3 tries (500ms, 1s, 2s) using `Last-Event-ID`/`?after=<n>` if `/api/runs/{id}/events` supports it, else restart. 404 unknown graph -> repo switcher falls back to first of `/api/repos`. Zero-result query -> row shows "0 rows" in dim, agent feed continues; if investigation yields no nodes: "Nothing in the graph matches `x`. Try a service name like opentelemetry-sdk" with 3 suggestions from `/critical`.
- Replay mode: `/api/replays` list -> dropdown; pill in top bar "REPLAY - research_otel_api" (violet) vs "LIVE" (green dot pulsing). Controls: play/pause, speed 1x/2x/4x, scrubber over event index (scrub = reset + fast-apply events 0..i with animations disabled, then resume), "Go live" button. Replay uses identical Director so judges see the same experience with no LLM/network dependency. `?replay=<name>&autoplay=1` deep link; also auto-fallback when `/api/health` fails.

## Prioritized implementation checklist

**P0 (demo-critical, ~first)**
1. Split into index.html/app.js/style.css; state object (`graph`, `nodes`, `links`, `paths`, `activePath`, `queries[]`); SSE client dispatching to Director queue.
2. Hero overlay + Run demo button + 3 scenario chips (+ replay fallback).
3. Incremental graph merge (no layout reset), label colors + shapes, PageRank/degree sizing.
4. Hop-by-hop path animation + queue catch-up policy.
5. Under the hood: query rows with ms/rows chips, Cypher highlighting, copy button, totals bar (queries/total/p95).
6. Claims -> click highlights path + zoomToFit; node hover tooltip.
7. Error/loading states; desktop 3-pane layout.

**P1**
8. Replay mode controls (play/pause/speed) + LIVE/REPLAY pill.
9. Schema meta-graph modal with run-time glow.
10. Repo switcher; memory timeline with Pull-into-graph.
11. Expand (double-click/`e`) with cluster nodes, label filter chips, node cap eviction.
12. Lens: PageRank + Blast depth (client BFS); mobile bottom-sheet layout.
13. Tool grouping in Under the hood, query-row hover halos; `a11y` live region + reduced motion.

**P2**
14. Community lens + `/scores` and `/blast` endpoints; `offset` on `/expand`.
15. Scrubber, shareable `#claim=` URLs, query-bar sparkline, table view, keyboard overlay, light theme, label-sector force.
