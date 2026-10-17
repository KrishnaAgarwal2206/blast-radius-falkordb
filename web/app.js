// Blast Radius UI — vanilla ES module, force-graph via CDN. Everything shown comes from the SSE stream / REST API.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const PALETTE = { Repo: '#F0E442', Service: '#56B4E9', File: '#A3B1C6', Class: '#CC79A7', Function: '#2FBF9A', Package: '#E69F00', Person: '#C4B5FD', Commit: '#7C8CF8', Incident: '#FF5A4A' };
const SCENARIOS = [
  { id: 'trace', label: '2 AM: metrics stopped exporting', sub: 'paste a real stack trace — periodic reader collect timeout', replay: 'scenario3',
    input: "Exception in thread Thread-3 (_ticker):\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.12/threading.py\", line 1075, in _bootstrap_inner\n    self.run()\n  File \"/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/metrics/_internal/export/__init__.py\", line 496, in _ticker\n    self.collect(timeout_millis=self._export_timeout_millis)\n  File \"/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/metrics/_internal/export/__init__.py\", line 316, in collect\n    metrics = self._collect(self, timeout_millis=timeout_millis)\n  File \"/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/metrics/_internal/measurement_consumer.py\", line 95, in collect\n    remaining_time = deadline_ns - time_ns()\nTimeoutError: Timed out while executing callback" },
  { id: 'svc', label: 'Service down', sub: 'opentelemetry-exporter-otlp-proto-grpc fails at startup', input: 'opentelemetry-exporter-otlp-proto-grpc', replay: 'scenario1' },
  { id: 'change', label: 'I’m changing this file', sub: 'sdk/metrics/_internal/view.py — blast radius + recurring defects', input: 'opentelemetry-sdk/src/opentelemetry/sdk/metrics/_internal/view.py', replay: 'scenario2' },
];
const S = { maxPR: 1, graph: 'otel', nodes: new Map(), links: new Map(), paths: {}, claims: [], active: null, lens: 'label', depth: new Map(), base: new Map(),
  q: { n: 0, ms: 0, list: [] }, es: null, pendingGroup: null, lit: new Map(), litLinks: new Map(), recalled: new Set(), replay: null, lastInput: null };
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------------------------------------------------------------- graph
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function shape(ctx, label, x, y, r) {
  ctx.beginPath();
  const poly = (n, rot = -Math.PI / 2, rr = r) => { for (let i = 0; i < n; i++) { const a = rot + (i * 2 * Math.PI) / n; ctx[i ? 'lineTo' : 'moveTo'](x + rr * Math.cos(a), y + rr * Math.sin(a)); } ctx.closePath(); };
  switch (label) {
    case 'Service': ctx.roundRect(x - r, y - r, 2 * r, 2 * r, r * 0.3); break;
    case 'File': ctx.rect(x - r * 0.8, y - r * 0.8, r * 1.6, r * 1.6); break;
    case 'Class': poly(4); break;
    case 'Package': poly(3); break;
    case 'Repo': poly(6, 0); break;
    case 'Incident': for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r * 0.5 : r * 1.2; ctx[i ? 'lineTo' : 'moveTo'](x + rr * Math.cos(a), y + rr * Math.sin(a)); } ctx.closePath(); break;
    default: ctx.arc(x, y, r, 0, 2 * Math.PI);
  }
}
const ease = (t) => 1 - Math.pow(1 - t, 3);
function rampPR(t) { const a = hex('#2A3A5C'), b = hex('#56B4E9'), c = hex('#FFF3B0'); const m = t < 0.5 ? [a, b, t * 2] : [b, c, (t - 0.5) * 2]; return `rgb(${m[0].map((v, i) => Math.round(v + (m[1][i] - v) * m[2])).join(',')})`; }
const DEPTH_COL = ['#FF5A4A', '#FFB000', '#F0E442', '#56B4E9'];
const COMM = ['#56B4E9', '#E69F00', '#CC79A7', '#2FBF9A', '#F0E442', '#C4B5FD', '#FF5A4A', '#7C8CF8', '#A3B1C6', '#3DDC97'];
function fillFor(n) {
  if (S.lens === 'pagerank') return n.label === 'Service' && n.pagerank != null ? rampPR(Math.sqrt(n.pagerank / S.maxPR)) : rampPR(Math.min(1, Math.log1p(S.deg?.get(n.id) || 0) / 3) * 0.6);
  if (S.lens === 'depth') return S.depth.has(n.id) ? DEPTH_COL[Math.min(S.depth.get(n.id), 3)] : '#3A4254';
  if (S.lens === 'community') return n.community != null ? COMM[n.community % COMM.length] : '#3A4254';
  return PALETTE[n.label] || '#999';
}
function radius(n) {
  if (n.label === 'Service') return 4 + 11 * Math.sqrt((n.pagerank || 0) / (S.maxPR || 1)) + (n.id === S.seed ? 3 : 0);
  return n.label === 'Incident' ? 6 : n.label === 'Commit' ? 5 : n.label === 'Function' ? 4 : 4.5;
}
const fg = ForceGraph()($('graph')).backgroundColor('rgba(0,0,0,0)').nodeId('id')
  .d3AlphaDecay(0.04).d3VelocityDecay(0.35).cooldownTicks(80)
  .nodeCanvasObjectMode(() => 'replace')
  .nodeCanvasObject((n, ctx, k) => {
    const now = performance.now(), L = S.lit.get(n.id), dim = S.active && !S.active.nodes.has(n.id);
    const born = Math.max(0, Math.min(1, (now - (n._born || 0)) / 350)), r = radius(n) * (reduced ? 1 : Math.max(0.05, 1 + 2.70158 * Math.pow(born - 1, 3) + 1.70158 * Math.pow(born - 1, 2)));
    ctx.globalAlpha = dim ? 0.12 : (S.running && !L && n.label !== 'Service') ? 0.5 : S.running && !L ? 0.3 : 1;
    shape(ctx, n.label, n.x, n.y, Math.max(r, 1));
    ctx.fillStyle = fillFor(n); ctx.fill();
    if (n.label === 'Person') { ctx.strokeStyle = '#0A0D14'; ctx.lineWidth = 1.2; ctx.stroke(); ctx.beginPath(); ctx.arc(n.x, n.y, r * 0.45, 0, 7); ctx.fillStyle = '#0A0D14'; ctx.fill(); }
    if (n.label === 'Commit') { ctx.beginPath(); ctx.arc(n.x, n.y, r * 0.3, 0, 7); ctx.fillStyle = '#0A0D14'; ctx.fill(); }
    if (L) {
      const p = (now - L) / 500; ctx.globalAlpha = 1; shape(ctx, n.label, n.x, n.y, Math.max(r, 1)); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6 / k; ctx.stroke();
      if (p < 1 && !reduced) { ctx.beginPath(); ctx.arc(n.x, n.y, r * (1 + 1.4 * ease(p)), 0, 7); ctx.strokeStyle = `rgba(255,176,0,${0.8 * (1 - p)})`; ctx.lineWidth = 2 / k; ctx.stroke(); }
    }
    if (n.id === S.seed) { ctx.globalAlpha = 1; ctx.setLineDash([3 / k, 2 / k]); ctx.beginPath(); ctx.arc(n.x, n.y, r + 4, 0, 7); ctx.strokeStyle = '#FF6B4A'; ctx.lineWidth = 1.2 / k; ctx.stroke(); ctx.setLineDash([]); }
    if (((L && (k > 1.6 || (n.label === 'Service' ? r > 8 : ['Commit', 'Person', 'Incident'].includes(n.label)))) || k > 2.6 || r > 11 || n === S.hover) && !dim) {
      ctx.globalAlpha = 1; ctx.font = `${11 / k}px Inter, sans-serif`; ctx.fillStyle = '#E8ECF4'; ctx.textBaseline = 'middle';
      ctx.fillText(short(n), n.x + r + 3 / k, n.y); }
    ctx.globalAlpha = 1;
  })
  .nodePointerAreaPaint((n, c, ctx) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(radius(n), 5), 0, 7); ctx.fill(); })
  .linkCanvasObjectMode(() => 'replace')
  .linkCanvasObject((l, ctx, k) => {
    const lit = S.litLinks.get(l.id), act = S.active && S.active.links.has(l.id), now = performance.now();
    const a = l.source, b = l.target; if (a.x == null || b.x == null) return;
    const p = lit ? Math.min(1, (now - lit) / 400) : 1, e = reduced ? 1 : ease(p);
    ctx.globalAlpha = S.active ? (act ? 1 : 0.06) : (lit || !S.running ? 0.9 : 0.18);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(a.x + (b.x - a.x) * (lit ? e : 1), a.y + (b.y - a.y) * (lit ? e : 1));
    ctx.strokeStyle = lit || act ? '#FFB000' : '#3a4560'; ctx.lineWidth = (lit || act ? 2.6 : 0.8) / k;
    if (lit || act) { ctx.shadowColor = '#FFB000'; ctx.shadowBlur = 8; } ctx.stroke(); ctx.shadowBlur = 0;
    if ((lit || act) && p >= 1) { const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, ang = Math.atan2(b.y - a.y, b.x - a.x);
      ctx.beginPath(); ctx.moveTo(b.x - 9 * Math.cos(ang) + 3 * Math.sin(ang), b.y - 9 * Math.sin(ang) - 3 * Math.cos(ang)); ctx.lineTo(b.x - 5 * Math.cos(ang), b.y - 5 * Math.sin(ang)); ctx.lineTo(b.x - 9 * Math.cos(ang) - 3 * Math.sin(ang), b.y - 9 * Math.sin(ang) + 3 * Math.cos(ang)); ctx.fillStyle = '#FFB000'; ctx.fill();
      if (k > 1.1 || act) { ctx.font = `${9 / k}px JetBrains Mono, monospace`; ctx.fillStyle = '#FFB000'; ctx.fillText(l.type, mx, my - 3 / k); } }
    ctx.globalAlpha = 1;
  })
  .linkDirectionalParticles((l) => (S.litLinks.has(l.id) && !reduced ? 2 : 0)).linkDirectionalParticleWidth(3).linkDirectionalParticleColor(() => '#FFB000')
  .onNodeHover((n) => { S.hover = n; showTip(n); })
  .onNodeClick((n) => expand(n))
  .onZoom(() => { S.userMoved = performance.now(); });
fg.d3Force('charge').strength(-70).distanceMax(260);
fg.d3Force('link').distance(38);
const sizeGraph = () => fg.width($('stage').clientWidth).height($('stage').clientHeight);
addEventListener('resize', sizeGraph); sizeGraph();
const short = (n) => { const k = n.name || n.key || n.id.split(':').slice(1).join(':'); if (n.label === 'File') return String(n.key || k).split('/').slice(-2).join('/'); if (n.label === 'Commit') return String(n.key || k).slice(0, 8); if (n.label === 'Function') return String(n.key || k).split('.').slice(-2).join('.'); return String(k).replace(/^opentelemetry-/, 'otel-').slice(0, 38); };
function addNodes(ns, near) {
  let added = 0;
  ns.forEach((n) => {
    const old = S.nodes.get(n.id);
    if (old) { Object.assign(old, n); return; }
    const o = near && S.nodes.get(near);
    const node = { ...n, key: n.key ?? n.id.split(':').slice(1).join(':'), _born: performance.now() + added * 25, x: o ? o.x + (Math.random() - 0.5) * 16 : undefined, y: o ? o.y + (Math.random() - 0.5) * 16 : undefined };
    S.nodes.set(n.id, node); added++;
  });
  return added;
}
function addLinks(ls) { ls.forEach((l) => { if (S.nodes.has(l.source) && S.nodes.has(l.target) && !S.links.has(l.id)) S.links.set(l.id, { ...l }); }); }
const sync = () => { S.deg = new Map(); S.links.forEach((l) => { const a = idOf(l.source), b = idOf(l.target); S.deg.set(a, (S.deg.get(a) || 0) + 1); S.deg.set(b, (S.deg.get(b) || 0) + 1); }); fg.graphData({ nodes: [...S.nodes.values()], links: [...S.links.values()] }); $('tN').textContent = S.nodes.size; };
const idOf = (x) => (typeof x === 'object' ? x.id : x);
function fitTo(pred, pad = 90, maxK = 2.4, ms = 600) {
  const ns = [...S.nodes.values()].filter((n) => n.x != null && (!pred || pred(n)));
  if (!ns.length) return fg.zoomToFit(ms, pad);
  const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const W = $('stage').clientWidth, H = $('stage').clientHeight, k = Math.min(maxK, (W - 2 * pad) / Math.max(x1 - x0, 1), (H - 2 * pad) / Math.max(y1 - y0, 1));
  fg.centerAt((x0 + x1) / 2, (y0 + y1) / 2, ms); fg.zoom(k, ms);
}
function fit(filter, pad = 70) { if (performance.now() - (S.userMoved || 0) < 2500 && !filter) return; fitTo(filter, pad); }

// ---------------------------------------------------------------- base (overview) layer
async function loadOverview() {
  S.nodes.clear(); S.links.clear(); S.lit.clear(); S.litLinks.clear(); S.depth.clear(); S.active = null; S.seed = null;
  try {
    const o = await (await fetch(`/api/graph/${S.graph}/overview`)).json();
    S.maxPR = Math.max(...o.nodes.map((n) => n.pagerank || 0), 1e-9);
    S.baseLinks = o.edges; addNodes(o.nodes); addLinks(o.edges);
    S.base = new Map(o.nodes.map((n) => [n.id, n]));
    sync(); setTimeout(() => fg.zoomToFit(400, 60), 600);
    o.queries.forEach((q) => S.overviewQ = (S.overviewQ || []).concat(q));
  } catch (e) { S.baseErr = e; }
}
async function loadMeta() {
  try {
    const repos = await (await fetch('/api/repos')).json();
    $('repo').innerHTML = repos.map((r) => `<option value="${esc(r.graph)}"${r.graph === S.graph ? ' selected' : ''}>${esc(r.graph)} (${r.nodes.toLocaleString()} nodes)</option>`).join('');
    if (!repos.find((r) => r.graph === S.graph) && repos[0]) { S.graph = repos[0].graph; }
    const st = await (await fetch(`/api/graph/${S.graph}/stats`)).json();
    const nn = Object.values(st.nodes).reduce((a, b) => a + b, 0), ee = Object.values(st.edges).reduce((a, b) => a + b, 0);
    $('heroStat').textContent = `${nn.toLocaleString()} nodes · ${ee.toLocaleString()} edges · ${Object.keys(st.nodes).length} labels · FalkorDB`;
    $('pill').className = 'pill live'; $('pill').textContent = 'LIVE';
    S.online = true;
  } catch (e) { S.online = false; $('heroStat').textContent = 'API/FalkorDB not reachable — demo scenarios will play recorded replays'; }
  loadMemory();
}
$('repo').onchange = async (e) => { S.es?.close(); S.graph = e.target.value; reset(); await loadOverview(); loadMeta(); };

// ---------------------------------------------------------------- run lifecycle
function reset() {
  S.paths = {}; S.claims = []; S.active = null; S.lit.clear(); S.litLinks.clear(); S.depth.clear(); S.seed = null; S.running = false; S.recalled.clear();
  S.q = { n: 0, ms: 0, list: [] }; S.pendingGroup = null; S.groups = {}; queue.length = 0;
  ['tQ', 'tMs'].forEach((i) => $(i).textContent = '0'); $('tP95').textContent = '–';
  $('tab-hood').innerHTML = '<div class="empty">Waiting for the first query…</div>'; $('tab-answer').innerHTML = '<div class="empty">Investigating…</div>'; $('feed').innerHTML = '';
  // drop everything that is not the base service map
  [...S.nodes.keys()].forEach((id) => { if (!S.base.has(id)) S.nodes.delete(id); }); S.links.clear();
  [...S.base.keys()].length && addLinks(S.baseLinks || []);
}
async function start(input, { llm = false, replay = null } = {}) {
  S.es?.close(); S.lastInput = input; S.userTab = false; reset(); $('hero').classList.add('gone'); selectTab('hood');
  $('inp').value = input || $('inp').value; S.running = true; sync();
  let url;
  if (replay) { url = `/api/replays/${replay}`; $('pill').className = 'pill replay'; $('pill').textContent = `REPLAY · ${replay}`; }
  else {
    $('pill').className = 'pill live'; $('pill').textContent = 'LIVE';
    let r;
    try { r = await fetch('/api/investigate', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ input, llm, graph: S.graph }) }); }
    catch (e) { return fail('Cannot reach the API.', input); }
    if (!r.ok) { let d = ''; try { d = (await r.json()).detail; } catch {} return fail(d || `Request failed (${r.status})`, input); }
    url = `/api/runs/${(await r.json()).run_id}/events`;
  }
  const es = new EventSource(url); S.es = es; let got = false;
  es.onmessage = (m) => { got = true; const e = JSON.parse(m.data); push(e); if (e.type === 'run_finished') es.close(); };
  es.onerror = () => { es.close(); if (!got) fail('Event stream failed.', input); };
}
function fail(msg, input) {
  S.running = false; const sc = SCENARIOS.find((s) => s.input === input);
  $('tab-answer').innerHTML = `<div class="err-box"><b>${esc(msg)}</b><br><button id="retry">Retry</button> ${sc ? '<button id="rp" class="ghost">Play recorded replay</button>' : ''}</div>`;
  $('retry').onclick = () => start(input); if (sc) $('rp').onclick = () => start(sc.input, { replay: sc.replay }); selectTab('answer');
}

// ---------------------------------------------------------------- director (queue keeps animation in step with the stream)
const queue = []; let busy = false;
function push(e) { e._at = performance.now(); queue.push(e); if (!busy) pump(); }
function pump() {
  const e = queue.shift(); if (!e) { busy = false; return; }
  busy = true; const lag = performance.now() - e._at, k = reduced ? 8 : Math.min(4, Math.max(1, 1 + (lag - 500) / 1000));
  const d = handle(e, k, lag > 2000);
  setTimeout(pump, Math.max(0, d / k));
}
function handle(e, k, skip) {
  switch (e.type) {
    case 'run_started': feed(`▶ ${e.mode} run on graph “${e.graph}”`, 't'); return 150;
    case 'thinking': feed(e.text, ''); return 0;
    case 'tool_call': openGroup(e); feed(`${e.tool}(${JSON.stringify(e.args).slice(0, 70)})`, 't'); return 120;
    case 'graph_query': addQuery(e); return 90;
    case 'tool_result': closeGroup(e); feed(`✓ ${e.summary}`, ''); markRecalled(e); return 80;
    case 'subgraph': {
      const near = [...S.nodes.keys()].find((id) => S.lit.has(id));
      const n = addNodes(e.nodes, near); addLinks(e.edges); sync(); return skip ? 0 : Math.min(600, n * 25 + 120); }
    case 'path': return animatePath(e, k, skip);
    case 'claim': S.claims.push(e); return 40;
    case 'error': feed(`! ${e.message}`, 'e'); toast(e.message); return 100;
    case 'draft_answer': finish({ answer: e.answer, ms: '…', cost_usd: '…' }); feed('Graph answer ready; LLM is reviewing it…', 't'); return 0;
    case 'run_finished': S.running = false; finish(e); return 0;
  }
  return 0;
}
function animatePath(p, k, skip) {
  S.paths[p.path_id] = { ...p, nodeSet: new Set(p.nodes) };
  const edgeIds = p.nodes.slice(1).map((n, i) => `${p.nodes[i]}|${p.rels[i]}|${n}`);
  p.nodes.forEach((id, i) => setTimeout(() => {
    S.lit.set(id, performance.now());
    if (i > 0) S.litLinks.set(edgeIds[i - 1], performance.now());
    if (i === p.nodes.length - 1 && p.path_id.startsWith('impact')) S.seed = S.seed || id;
  }, skip || reduced ? 0 : (i * 450) / k));
  if (p.path_id.startsWith('impact')) { // blast depth lens: depth = hop distance to the failing node (last node of each path)
    const tgt = p.nodes[p.nodes.length - 1]; S.seed = tgt; S.depth.set(tgt, 0);
    p.nodes.forEach((id, i) => S.depth.set(id, Math.min(S.depth.get(id) ?? 99, p.nodes.length - 1 - i)));
  }
  setTimeout(() => { sync(); if (!S.active) fit((n) => S.lit.has(n.id), 90); }, skip ? 0 : (p.nodes.length * 450) / k);
  return skip ? 0 : Math.min(p.nodes.length * 450, 2400);
}
function markRecalled(e) { (e.node_ids || []).forEach((id) => { if (id.startsWith('Incident:')) { S.recalled.add(id.slice(9)); document.querySelector(`[data-inc="${CSS.escape(id.slice(9))}"]`)?.classList.add('recalled'); } }); }

// ---------------------------------------------------------------- panels
function feed(t, cls) { const d = document.createElement('div'); d.className = cls; d.textContent = t; const f = $('feed'); f.appendChild(d); while (f.children.length > 40) f.firstChild.remove(); f.scrollTop = 1e9; }
function toast(m) { const d = document.createElement('div'); d.className = 'err-box'; d.textContent = m; const t = $('tab-hood'); t.prepend(d); setTimeout(() => d.remove(), 6000); }
function selectTab(n) { document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === n)); $('tab-answer').hidden = n !== 'answer'; $('tab-hood').hidden = n !== 'hood'; }
document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => { S.userTab = true; selectTab(b.dataset.tab); }));
function highlight(c) {
  const lines = esc(c).replace(/(--[^\n]*)/g, '<span class="cm">$1</span>');
  return lines.replace(/(&#39;(?:[^&]|&(?!#39;))*&#39;)|(\$\w+)|(\[:[A-Z_|]+(?:\*[\d.]*)?\])|(:[A-Za-z_]\w*)|\b(\d+(?:\.\d+)?)\b|\b(MATCH|OPTIONAL|WHERE|RETURN|WITH|ORDER BY|LIMIT|CALL|YIELD|AS|IN|AND|OR|NOT|DISTINCT|UNWIND|CREATE|MERGE|SET|ENDS WITH|CONTAINS|ON|DESC|COALESCE|NULL|IS)\b|\b([a-zA-Z_.]+)\(/g,
    (m, s, p, r, l, nu, kw, fn) => s ? `<span class="st2">${s}</span>` : p ? `<span class="pm">${p}</span>` : r ? `<span class="rl">${r}</span>` : l ? `<span class="lb">${l}</span>` : nu ? `<span class="nu">${nu}</span>` : kw ? `<span class="kw">${kw}</span>` : `<span class="fn">${fn}</span>(`);
}
function openGroup(e) {
  const hood = $('tab-hood'); if (hood.querySelector('.empty')) hood.innerHTML = '';
  const g = document.createElement('div'); g.className = 'grp'; g.innerHTML = `<header><span class="tool">${esc(e.tool)}</span><span class="args">${esc(JSON.stringify(e.args).slice(0, 60))}</span><span class="st">running…</span></header>`;
  hood.appendChild(g); (S.groups ||= {})[e.call_id] = { el: g, n: 0, ms: 0 }; hood.scrollTop = 1e9;
}
function addQuery(e) {
  const G = S.groups?.[e.call_id]; if (!G) return; G.n++; G.ms += e.ms; S.q.n++; S.q.ms += e.ms; S.q.list.push(e.ms);
  const cls = e.ms < 20 ? 'g' : e.ms < 100 ? 'a' : 'r', mx = Math.max(...S.q.list, 1);
  const q = document.createElement('div'); q.className = 'q';
  q.innerHTML = `<div class="chips"><span class="c ${cls}">${e.ms} ms</span><span class="c">${e.rows} rows</span><button class="ghost cp">Copy</button></div><pre class="cy">${highlight(e.cypher)}</pre><div class="bar"><i style="width:${Math.max(3, (e.ms / mx) * 100)}%"></i></div>`;
  q.querySelector('pre').onclick = (ev) => ev.currentTarget.classList.toggle('open');
  q.querySelector('.cp').onclick = async (ev) => { try { await navigator.clipboard.writeText(e.cypher); ev.target.textContent = 'Copied'; setTimeout(() => (ev.target.textContent = 'Copy'), 1200); } catch {} };
  G.el.appendChild(q); $('tab-hood').scrollTop = 1e9;
  $('tQ').textContent = S.q.n; $('tMs').textContent = S.q.ms.toFixed(1);
  const s = [...S.q.list].sort((a, b) => a - b); $('tP95').textContent = s[Math.min(s.length - 1, Math.ceil(s.length * 0.95) - 1)].toFixed(1);
}
function closeGroup(e) { const G = S.groups?.[e.call_id]; if (G) G.el.querySelector('.st').textContent = `${G.n} queries · ${G.ms.toFixed(1)} ms`; }
function finish(e) {
  const a = e.answer, box = $('tab-answer'); if (!S.userTab) selectTab('answer');
  if (!a) { box.innerHTML = `<div class="err-box"><b>No answer.</b> ${esc(S.lastError || 'Nothing in the graph matched that input. Try a service name such as opentelemetry-sdk, or paste a Python traceback.')}</div>`; return; }
  box.innerHTML = `<div class="summary">${esc(a.summary)}</div><div class="meta">${e.ms ?? ''} ms · ${S.q.n} FalkorDB queries (${S.q.ms.toFixed(1)} ms) · confidence ${a.confidence ?? '–'} · LLM cost $${e.cost_usd ?? 0}</div>
  <div class="meta">Click a claim to highlight its exact graph path.</div>`;
  a.claims.forEach((c) => {
    const b = document.createElement('button'); b.className = 'claim'; b.setAttribute('aria-pressed', 'false');
    const ps = c.path_ids.map((p) => S.paths[p]?.sentence).filter(Boolean);
    b.innerHTML = `<span class="kind">${esc(c.kind)}</span><br>${esc(c.text)}${ps.map((s) => `<span class="path">${esc(s)}</span>`).join('')}`;
    b.onclick = () => selectClaim(c, b); box.appendChild(b);
  });
  const n = Object.values(S.paths).length; feed(`Done. ${a.claims.length} claims, ${n} evidence paths.`, 't');
  if (a.dropped_unverified_claims) feed(`${a.dropped_unverified_claims} claim(s) dropped: no graph path`, 'e');
  setTimeout(() => fitTo((n) => S.lit.has(n.id), 80, 1.6), 300);
}
function selectClaim(c, btn) {
  const on = btn.getAttribute('aria-pressed') !== 'true';
  document.querySelectorAll('.claim').forEach((x) => x.setAttribute('aria-pressed', 'false'));
  if (!on) { S.active = null; return; }
  btn.setAttribute('aria-pressed', 'true');
  const nodes = new Set(), links = new Set();
  c.path_ids.forEach((id) => { const p = S.paths[id]; if (!p) return; p.nodes.forEach((n) => nodes.add(n)); p.nodes.slice(1).forEach((n, i) => links.add(`${p.nodes[i]}|${p.rels[i]}|${n}`)); });
  c.node_ids?.forEach((id) => S.nodes.has(id) && nodes.add(id)); S.active = { nodes, links }; S.lit = new Map([...nodes].map((n) => [n, performance.now() - 1000])); S.litLinks = new Map([...links].map((l) => [l, performance.now() - 1000]));
  fitTo((n) => nodes.has(n.id), 110);
}
addEventListener('keydown', (e) => { if (e.key === 'Escape') { S.active = null; document.querySelectorAll('.claim').forEach((x) => x.setAttribute('aria-pressed', 'false')); }
  if (e.target.matches('textarea,input,select')) return; if (e.key === '/') { e.preventDefault(); $('inp').focus(); }
  if ('1234'.includes(e.key) && e.key) setLens(['label', 'pagerank', 'depth', 'community'][+e.key - 1]); });

// ---------------------------------------------------------------- hover / expand
const propCache = new Map();
async function showTip(n) {
  const t = $('tip'); if (!n) { t.hidden = true; return; }
  const draw = (props) => { t.innerHTML = `<b style="color:${PALETTE[n.label]}">${esc(n.label)}</b> ${esc(short(n))}<br>${Object.entries(props || {}).slice(0, 6).map(([k, v]) => `<span class="k">${esc(k)}</span> <span class="v">${esc(String(v).slice(0, 60))}</span>`).join('<br>')}${n.pagerank != null ? `<br><span class="k">pagerank</span> <span class="v">${n.pagerank.toFixed(5)}</span>` : ''}<br><span class="k">click to expand neighbours</span>`; };
  t.hidden = false; draw(propCache.get(n.id));
  if (!propCache.has(n.id)) { try { const r = await (await fetch(`/api/graph/${S.graph}/subgraph?ids=${encodeURIComponent(n.id)}`)).json(); propCache.set(n.id, r.nodes[0]?.props || {}); if (S.hover === n) draw(propCache.get(n.id)); } catch {} }
}
addEventListener('mousemove', (e) => { const t = $('tip'), r = $('stage').getBoundingClientRect(); t.style.left = Math.min(e.clientX - r.left + 14, r.width - 330) + 'px'; t.style.top = Math.max(0, e.clientY - r.top + 14) + 'px'; });
async function expand(n) {
  try {
    const r = await (await fetch(`/api/graph/${S.graph}/expand?id=${encodeURIComponent(n.id)}&limit=14`)).json();
    r.queries?.forEach((q) => { S.q.n++; S.q.ms += q.ms; S.q.list.push(q.ms); }); $('tQ').textContent = S.q.n; $('tMs').textContent = S.q.ms.toFixed(1);
    addNodes(r.nodes, n.id); addLinks(r.edges); sync();
    if (r.queries?.[0]) { const hood = $('tab-hood'); if (hood.querySelector('.empty')) hood.innerHTML = ''; openGroup({ call_id: 'x' + S.q.n, tool: 'expand', args: { id: n.id } }); addQuery({ call_id: 'x' + S.q.n, ...r.queries[0] }); closeGroup({ call_id: 'x' + S.q.n }); }
  } catch {}
}

// ---------------------------------------------------------------- lens, legend
function setLens(l) { S.lens = l; document.querySelectorAll('#lens button').forEach((b) => b.classList.toggle('on', b.dataset.lens === l)); legend(); }
document.querySelectorAll('#lens button').forEach((b) => (b.onclick = () => setLens(b.dataset.lens)));
function legend() {
  const L = $('legend');
  if (S.lens === 'label') L.innerHTML = Object.entries(PALETTE).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join('');
  else if (S.lens === 'pagerank') L.innerHTML = '<span>Services colored/sized by FalkorDB algo.pageRank over DEPENDS_ON (bright = many things depend on it)</span>';
  else if (S.lens === 'depth') L.innerHTML = DEPTH_COL.map((c, i) => `<span><i style="background:${c}"></i>${i === 0 ? 'failing node' : i === 3 ? '3+ hops' : i + ' hop'}</span>`).join('') + '<span>(from the blast_radius paths of this run)</span>';
  else L.innerHTML = '<span>Services colored by FalkorDB algo.labelPropagation community</span>';
}
legend();

// ---------------------------------------------------------------- schema modal
let sg;
$('btnSchema').onclick = async () => {
  $('modal').hidden = false;
  const s = await (await fetch(`/api/graph/${S.graph}/schema`)).json(); const mx = Math.max(...Object.values(s.labels));
  const nodes = Object.entries(s.labels).map(([id, n]) => ({ id, n })), links = s.patterns.map((p) => ({ source: p.a, target: p.b, type: p.type, n: p.n }));
  sg ||= ForceGraph()($('schemaGraph')).backgroundColor('#111622');
  sg.width($('schemaGraph').clientWidth).height(430).nodeId('id').nodeRelSize(1).linkCurvature((l) => (l.source === l.target || l.source.id === l.target.id ? 0.7 : 0.15))
    .nodeCanvasObject((n, ctx, k) => { const r = 6 + 14 * Math.sqrt(n.n / mx); shape(ctx, n.id, n.x, n.y, r); ctx.fillStyle = PALETTE[n.id]; ctx.fill(); ctx.font = `${11 / k}px Inter`; ctx.fillStyle = '#E8ECF4'; ctx.textAlign = 'center'; ctx.fillText(`${n.id} ${n.n.toLocaleString()}`, n.x, n.y + r + 9 / k); })
    .linkWidth((l) => 0.6 + Math.log(l.n + 1) / 3).linkColor(() => '#56627f').linkDirectionalArrowLength(4).linkDirectionalArrowRelPos(1)
    .linkCanvasObjectMode(() => 'after').linkCanvasObject((l, ctx, k) => { if (l.source.x == null) return; ctx.font = `${8 / k}px JetBrains Mono`; ctx.fillStyle = '#FFB000'; ctx.textAlign = 'center'; ctx.fillText(`${l.type} ${l.n.toLocaleString()}`, (l.source.x + l.target.x) / 2, (l.source.y + l.target.y) / 2); })
    .graphData({ nodes, links });
  setTimeout(() => sg.zoomToFit(300, 30), 900);
};
$('mClose').onclick = () => ($('modal').hidden = true);

// ---------------------------------------------------------------- memory timeline
async function loadMemory() {
  try {
    const inc = await (await fetch(`/api/incidents?graph=${S.graph}&limit=200`)).json();
    $('memCount').textContent = `(${inc.length} incidents)`;
    $('memBody').innerHTML = inc.map((i) => `<div class="inc${S.recalled.has(i.id) ? ' recalled' : ''}" data-inc="${esc(i.id)}"><b>${esc((i.title || '').slice(0, 80))}</b><small>${esc(i.id)} · ${i.source} · ${new Date(i.ts * 1000).toISOString().slice(0, 10)}${i.cause ? ' · cause ' + esc(i.cause.slice(0, 8)) : ''}</small><br><button class="ghost" data-pull="${esc(i.id)}">Pull into graph</button></div>`).join('');
    $('memBody').querySelectorAll('[data-pull]').forEach((b) => (b.onclick = async () => {
      const id = 'Incident:' + b.dataset.pull; $('hero').classList.add('gone');
      const base = await (await fetch(`/api/graph/${S.graph}/subgraph?ids=${encodeURIComponent(id)}`)).json(); addNodes(base.nodes.map((n) => ({ ...n, key: n.id.split(':').slice(1).join(':'), name: (n.props.title || '').slice(0, 40) })));
      sync(); await expand(S.nodes.get(id)); S.lit.set(id, performance.now()); fg.zoomToFit(600, 100, (n) => n.id === id || S.links.has(`${id}|AFFECTED|${n.id}`) || S.links.has(`${id}|CAUSED_BY|${n.id}`) || S.links.has(`${id}|RESOLVED_BY|${n.id}`));
    }));
  } catch {}
}
$('memToggle').onclick = () => { $('memBody').hidden = !$('memBody').hidden; sizeGraph(); };

// ---------------------------------------------------------------- wiring
$('chips').innerHTML = SCENARIOS.map((s, i) => `<button class="chip" data-i="${i}">${esc(s.label)}<small>${esc(s.sub)}</small></button>`).join('');
document.querySelectorAll('.chip').forEach((b) => (b.onclick = () => { const s = SCENARIOS[+b.dataset.i]; runScenario(s); }));
function runScenario(s) { $('inp').value = s.input; start(s.input, { llm: $('llm').checked, replay: S.online ? null : s.replay }); }
$('go').onclick = () => { const v = $('inp').value.trim(); if (!v) { $('inp').focus(); return; } start(v, { llm: $('llm').checked }); };
$('inp').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('go').click(); });
$('heroGo').onclick = () => runScenario(SCENARIOS[0]);
const params = new URLSearchParams(location.search);
(async () => {
  if (params.get('g')) S.graph = params.get('g');
  await loadMeta(); await loadOverview();
  if (params.get('replay')) start('', { replay: params.get('replay') });
})();
