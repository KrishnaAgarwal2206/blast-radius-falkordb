# FalkorDB Research (for Blast Radius)

Tested against `falkordb/falkordb:latest` (Redis 8.10.2, graph module ver 42201) + Python `falkordb` 1.8.0 on Docker 28.0.1, 2026-10-17.
Legend: [T] = executed and verified; [U] = untested (docs only).

## 1. Hackathon facts
Source: https://www.wemakedevs.org/hackathons/falkordb (+ /rules)
- Graph Hacks: Context for AI Agents, Oct 15-18 2026 (IST), online, teams of 1-4, $20k total.
- Tracks: (1) Agents That Act on Connected Data (multi-hop reasoning, graph queries as agent tools), (2) Agent Memory and Coordination, (3) Company Brain. Prizes per track (iPhone / PS5 / Mac Mini), plus AirPods for best blog post, T-shirts for top 50.
- Hard rule: "FalkorDB must be the primary graph database, and it must support a central part of the product" (project must not work without it).
- Submission: public repo; README with setup and data model; **the Cypher queries / graph algorithms the product depends on** (document these!); demo video; live deployment (preferred) or local setup instructions; track designation.
- New work during event only (libraries/templates OK). AI assistants allowed if disclosed; fully AI-generated with no human understanding may be rejected.
- Judging: how well graph connections are used for agent reasoning, memory persistence, explainability, real-world utility. Blast Radius fits Track 1 (agent tool = graph query for impact analysis; explainable via returned paths).

## 2. Setup
- Local: `docker run -p 6379:6379 -p 3000:3000 -it --rm falkordb/falkordb:latest` [T: image runs; I used `-d --name`]. Port 6379 = Redis protocol, 3000 = FalkorDB Browser (HTTP 200 verified). Without a volume `--rm` loses data; add `-v fdbdata:/var/lib/falkordb/data` for persistence [U].
- Browser UI at http://localhost:3000: run Cypher, see graph visualization; good for demo screenshots.
- Server defaults (GRAPH.CONFIG GET *) [T]: **TIMEOUT=1000 ms** (queries are killed after 1s by default!), RESULTSET_SIZE=10000, MAX_QUEUED_QUERIES=25, CACHE_SIZE=25, THREAD_COUNT=16. Raise via `GRAPH.CONFIG SET TIMEOUT_MAX 30000` / `TIMEOUT_DEFAULT` or per-query `timeout=` in the client (needs TIMEOUT_MAX allowing it) [per-query timeout=5000 ran OK T].
- FalkorDB Cloud (https://docs.falkordb.com/cloud/free-tier): free tier, no credit card, signup app.falkordb.cloud/signup, AWS or GCP. Limits: 100MB RAM/dataset; stopped after 1 day unused, deleted after 7 days inactivity; no persistence/backups, no TLS, no HA. Paid from ~$73/month. Good enough for a demo of per-repo graphs of small/medium size; for the live demo, hit it once a day or keep a seed script to reload. Alternative: self-host the Docker image on Fly.io/Railway/a VPS.
- Connect to cloud: `FalkorDB(host=..., port=..., username=..., password=...)` [U] (ssl=True only if TLS enabled on paid tiers).

## 3. Clients
- Python: `pip install falkordb` (https://github.com/FalkorDB/falkordb-py, docs falkordb-py.readthedocs.io). Sync `FalkorDB`, async `falkordb.asyncio.FalkorDB` with `BlockingConnectionPool`. `pip install "falkordb[hiredis]"` optional speedup.
- `Graph.query(q, params, timeout)`, `ro_query`, `explain`, `profile`, `slowlog`, `copy`, `delete`; `db.list_graphs()`; `db.connection` is the raw redis-py client [all T].
- QueryResult: `.result_set` (list of rows), `.header` ([[type,name],...]), `.nodes_created`, `.relationships_created`, `.properties_set`, `.run_time_ms` (server-side execution time, float). Node: `.labels`, `.properties`, `.id` (internal, reused after deletes - don't use as stable ID). Path: `.nodes()`, `.edges()`.
- Node.js: `npm i falkordb` (6.8.0 on npm; https://github.com/FalkorDB/falkordb-ts) [U]: `const db = await FalkorDB.connect({socket:{host,port}}); const g = db.selectGraph('x'); await g.query('...', {params:{}})`.

## 4. Cypher dialect gotchas (vs Neo4j)
Verified [T] unless noted. Docs: https://docs.falkordb.com/cypher/ , known limitations https://docs.falkordb.com/cypher/known-limitations.html
- **Indexes**: `CREATE INDEX FOR (f:Function) ON (f.name)` (DDL, no names, single-property each; multi-prop = multiple statements). Neo4j `CREATE INDEX name FOR ... ON` style names not supported. Only equality/range/STARTS WITH use it, not `<>`. Index creation is async-ish; check `CALL db.indexes()`.
- **Unique constraints** are NOT Cypher DDL: need a range index on the property first, then raw command `GRAPH.CONSTRAINT CREATE g UNIQUE NODE Label PROPERTIES 1 id` (returns PENDING, then enforced: duplicate CREATE gave "unique constraint violation"). Without the index: "missing supporting exact-match index". Via Python: `db.connection.execute_command("GRAPH.CONSTRAINT","CREATE",graph,"UNIQUE","NODE","Function","PROPERTIES","1","id")`.
- **MERGE**: supported incl. `ON CREATE SET / ON MATCH SET`. MERGE on a full node pattern with many properties is slow without index on the key; MERGE with only the key `{id:...}` then SET the rest.
- **Variable-length paths**: `-[:CALLS*1..3]->` fine. Returned path values parse in Python as Path objects. `size(r)` on a path errors; use `length(p)`, `nodes(p)`, `relationships(p)`. Unbounded `*` over a dense graph can blow the 1s timeout: always bound depth.
- **shortestPath** only allowed in WITH/RETURN (not MATCH p=shortestPath(...)): `MATCH (a),(b) WITH shortestPath((a)-[:R*]->(b)) AS p RETURN length(p)`. **allShortestPaths** only in MATCH, with both endpoints already bound. Errors seen: "FalkorDB currently only supports shortestPaths in WITH or RETURN clauses".
- **Parameters**: `$name`, passed as dict (client builds a `CYPHER` prefix). Lists of maps via UNWIND work (bulk loading). Parameterized queries are plan-cached (CACHE_SIZE 25) - use params, not string interpolation.
- LIMIT does not stop eager ops (CREATE/SET/MERGE/aggregations run fully). No aggregation inside pattern comprehensions. Unknown property returns null (no error).
- Labels can be added: `SET a:Hot`. Multiple labels OK.
- **Full-text**: `CREATE FULLTEXT INDEX FOR (f:Function) ON (f.name)` then `CALL db.idx.fulltext.queryNodes('Function','handle*') YIELD node, score`. Tokenized on punctuation/whitespace (RediSearch): `handle_request3` is found by exact term; prefix `foo*`, fuzzy `%term%1`, OR `|`, NOT `-` per docs (fuzzy [U]; my typo test returned empty).
- **Vector**: `CREATE VECTOR INDEX FOR (f:Function) ON (f.emb) OPTIONS {dimension:3, similarityFunction:'cosine'}` (dimension 1-4096, cosine|euclidean, HNSW M/efConstruction/efRuntime). Store `vecf32([...])`. Query `CALL db.idx.vector.queryNodes('Function','emb',k,vecf32([...])) YIELD node, score` - score is a distance (identical vector gave 0.0, lower = closer for cosine) [T]. Property must be stored via vecf32 or it's not indexed.
- Introspection: `CALL db.labels()`, `db.relationshipTypes()`, `db.propertyKeys()`, `db.indexes()`, `dbms.procedures()` (lists all algo.* procs).

## 5. Native algorithms (verified names run on 2000-node graph [T])
Docs: https://docs.falkordb.com/algorithms/ . Procedures live in `algo.` namespace (case-insensitive: `algo.WCC` = `algo.wcc`; dbms.procedures shows `algo.BFS`, `algo.AStar`, ...). List: BFS, SPpaths, SSpaths, AStar, MSF, pageRank, betweenness, harmonic centrality, WCC, labelPropagation (CDLP), MaxFlow.
| Algo | Signature | Yields |
|---|---|---|
| PageRank | `CALL algo.pageRank(label|null, relType|null)` | node, score (sums to 1.0) |
| Betweenness | `CALL algo.betweenness({nodeLabels:[..], relationshipTypes:[..], samplingSize:int(32 default), samplingSeed:int})` | node, score (sampled approximation; raise samplingSize for accuracy) |
| WCC | `CALL algo.WCC({nodeLabels:[..], relationshipTypes:[..]})` (or `null`) | node, componentId (edges treated undirected) |
| CDLP | `CALL algo.labelPropagation({nodeLabels, relationshipTypes, maxIterations:10})` | node, communityId |
| BFS | `MATCH (s) CALL algo.bfs(s, maxDepth, relType|null) YIELD nodes, edges` | nodes (list), edges (list); BFS order, one row |
| Shortest path | `CALL algo.SPpaths({sourceNode, targetNode, relTypes:[..], weightProp, costProp, maxCost, maxLen, relDirection:'outgoing'|'incoming'|'both', pathCount:1})` | path, pathWeight, pathCost (weightProp optional: omitted = hop count worked [T]) |
| Single source | `algo.SSpaths({...})` | paths from one source [U] |
Notes: PageRank/betweenness are over the whole (label, rel) subgraph - good for "most critical/central function" ranking; WCC for "isolated modules"; CDLP for module clustering; BFS/var-length for blast radius; `relDirection:'incoming'` on SPpaths for reverse (callers) paths [U].

## 6. Multigraph / multi-tenant
- Graph = keyspace key; created implicitly on first write: `db.select_graph('repo:owner/name')`. `db.list_graphs()` [T], `g.delete()` [T, errors if graph doesn't exist], `g.copy('new')` [T]. Raw: `GRAPH.LIST`, `GRAPH.DELETE`.
- One graph per repo (and optionally `repo:name@sha` per commit for diffs; `copy` makes cheap snapshots) gives isolation, trivial teardown/re-index (`delete()` then reload), and per-tenant queries without a tenant property. Cross-graph queries are not possible: keep a small `meta` graph for the repo registry.

## 7. Integrations: fit for Blast Radius
| Option | What | Pros | Cons |
|---|---|---|---|
| FalkorDB MCP server (https://github.com/FalkorDB/FalkorDB-MCPServer, MIT, npm `@falkordb/mcpserver` 1.3.0) | Tools: query (read-only mode via FALKORDB_DEFAULT_READONLY), create nodes/rels, list/delete graphs, get_graph_schema/node/relationship schema. stdio or HTTP (MCP_TRANSPORT, MCP_PORT, MCP_API_KEY) | Zero-code way to let Claude/agents query the repo graph; good Track-1 story | Generic Cypher; agent must write queries. Better to ship OUR own MCP tools (`blast_radius(symbol)`, `callers`, `critical_nodes`) over the Python client, optionally alongside this one |
| GraphRAG-SDK v1.1.0 (https://github.com/FalkorDB/GraphRAG-SDK, Apache-2.0, `pip install graphrag-sdk[litellm]`) | LLM entity extraction from documents, provenance, multi-tenant | Good for docs/PR/issue text -> graph | Extraction is LLM-driven and slow/costly; code structure should come from a parser (tree-sitter/ast), not an LLM. Optional add-on for README/docs |
| Graphiti (`pip install graphiti-core[falkordb]`, `Graphiti(uri="falkor://localhost:6379")`, per-agent `graph_name`) | Temporal knowledge graph agent memory | Fits Track 2 memory (remember past analyses, incidents) | Needs OpenAI-style LLM+embedding keys, async-heavy, extra latency; overkill unless we pitch memory |
| LangChain/LlamaIndex (FalkorDBGraph, QA chain; docs.falkordb.com/integration) | Text-to-Cypher chains | Quick NL Q&A | LLM-generated Cypher is unreliable for algo.* calls; I could not fetch the docs page (404), [U] |
| QueryWeaver (https://github.com/FalkorDB/QueryWeaver, AGPL-3.0) | Text2SQL using a FalkorDB schema graph | Not relevant to code graphs | AGPL, SQL-focused; skip |
Recommendation: direct `falkordb` client + tree-sitter/ast parsing + our own MCP/tool layer; use native algo.* for ranking. Mention MCP server compatibility.

## 8. Performance
- Bulk load via batched UNWIND with params [T]: 2000 MERGE nodes (3 props each) in 22.9 ms server time (28 ms round trip); 2000 edges MERGE with 2 index lookups in 23 ms. Use batches of ~1k-5k rows, create index (and constraint) BEFORE loading, nodes first then edges. Keep batch payload moderate (RESULTSET_SIZE caps returned rows at 10000, not input).
- Latency display: `result.run_time_ms` is server execution time; wrap with `time.perf_counter()` for round trip. Show both in the UI ("graph query 0.2 ms; 7 hops"). Typical indexed lookups were ~0.15-0.2 ms [T]. `g.profile(q)` and `g.explain(q)` give plans [T]; `g.slowlog()` [T].
- Gotcha: default 1000 ms TIMEOUT also applies to heavy bulk/algorithm calls; raise TIMEOUT_MAX / pass `timeout=`.

## 9. Prior art (differentiate)
- FalkorDB Code-Graph (https://docs.falkordb.com/genai-tools/code-graph , repos FalkorDB/code-graph and code-graph-backend, demo code-graph.falkordb.com): Flask/FastAPI backend, GraphRAG-SDK chat, supports Python/Java/C#, shows classes/functions/files with calls/imports/inherits, visualization + "chat with your codebase". Blog: https://www.falkordb.com/blog/code-graph-is-the-secret/ ; Medium post visualising top AI repos with it.
- Differentiation for Blast Radius: change-centric not browse/chat-centric: input a diff/symbol -> ranked impact set with explainable paths (path returns), criticality via PageRank/betweenness, community-level (CDLP) blast, test coverage mapping, agent-callable tool/MCP returning paths as evidence, latency shown live. Support more languages (JS/TS) than the stock demo. Avoid just "ingest repo + chat".

## 10. Cheat sheet
All snippets Python unless noted. Setup: `from falkordb import FalkorDB; db = FalkorDB(host='localhost', port=6379); g = db.select_graph('repo:test')`.

1. [T] Run: `docker run -d --name fdb -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest` (add `-v fdbdata:/var/lib/falkordb/data` [U] for persistence)
2. [T] Connect: `db = FalkorDB(host='localhost', port=6379)`; cloud [U]: `FalkorDB(host=H, port=P, username=U, password=PW)`
3. [T] Indexes: `g.query("CREATE INDEX FOR (f:Function) ON (f.id)")`; `g.query("CREATE INDEX FOR (f:File) ON (f.path)")`
4. [T] Unique constraint (after index): `db.connection.execute_command("GRAPH.CONSTRAINT","CREATE","repo:test","UNIQUE","NODE","Function","PROPERTIES","1","id")`
5. [T] Bulk nodes: `g.query("UNWIND $rows AS r MERGE (f:Function {id:r.id}) SET f.name=r.name, f.file=r.file", {'rows': rows})`
6. [T] Bulk edges: `g.query("UNWIND $e AS e MATCH (a:Function {id:e.a}),(b:Function {id:e.b}) MERGE (a)-[:CALLS]->(b)", {'e': edges})`
7. [T] Merge w/ flags: `MERGE (f:Function {id:'zz'}) ON CREATE SET f.new=true ON MATCH SET f.seen=true RETURN f`
8. [T] Params + parse: `for [n] in g.query("MATCH (f:Function) WHERE f.name=$n RETURN f", {'n':'fn5'}).result_set: print(n.labels, n.properties)`
9. [T] Timing: `r = g.query(q, params); print(r.run_time_ms)` (server ms); `r.header`, `r.nodes_created`
10. [T] Read-only + timeout: `g.ro_query("MATCH (n) RETURN count(n)", timeout=5000).result_set`
11. [T] Blast radius (transitive callers, bounded): `MATCH (b:Function {id:$id})<-[:CALLS*1..4]-(a) RETURN DISTINCT a.id`
12. [T] Callers with distance: `MATCH (b:Function {id:'f5'})<-[:CALLS*1..3]-(a) RETURN a.id, min(length(shortestPath((a)-[:CALLS*]->(b))))`
13. [T] Path with explanation: `MATCH p=(a:Function {id:$id})-[:CALLS*1..3]->(b) RETURN length(p), [n IN nodes(p) | n.id]`; Python Path: `p.nodes()`, `p.edges()`
14. [T] Shortest path (WITH form): `MATCH (a:Function {id:'f1'}),(b:Function {id:'f8'}) WITH shortestPath((a)-[:CALLS*]->(b)) AS p RETURN length(p), [n IN nodes(p) | n.id]`
15. [T] SPpaths proc: `MATCH (a:Function {id:'f1'}),(b:Function {id:'f8'}) CALL algo.SPpaths({sourceNode:a, targetNode:b, relTypes:['CALLS'], pathCount:1}) YIELD path RETURN length(path)`
16. [T] PageRank: `CALL algo.pageRank('Function','CALLS') YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT 10`
17. [T] Betweenness: `CALL algo.betweenness({nodeLabels:['Function'], relationshipTypes:['CALLS'], samplingSize:64}) YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT 10`
18. [T] WCC: `CALL algo.WCC({nodeLabels:['Function'], relationshipTypes:['CALLS']}) YIELD node, componentId RETURN componentId, count(node) AS n ORDER BY n DESC`
19. [T] CDLP: `CALL algo.labelPropagation({maxIterations:10}) YIELD node, communityId RETURN communityId, count(node) AS n ORDER BY n DESC`
20. [T] BFS: `MATCH (s:Function {id:'f1'}) CALL algo.bfs(s, 3, 'CALLS') YIELD nodes, edges RETURN size(nodes), size(edges)`
21. [T] Full-text: `CREATE FULLTEXT INDEX FOR (f:Function) ON (f.name)` then `CALL db.idx.fulltext.queryNodes('Function','handle*') YIELD node, score RETURN node.id, score`
22. [T] Vector: `CREATE VECTOR INDEX FOR (f:Function) ON (f.emb) OPTIONS {dimension:3, similarityFunction:'cosine'}`; `SET f.emb = vecf32([1,0,0])`; `CALL db.idx.vector.queryNodes('Function','emb',5,vecf32([1,0,0])) YIELD node, score`
23. [T] Graph mgmt: `db.list_graphs()`; `db.select_graph('a').copy('b')`; `db.select_graph('a').delete()`
24. [T] Introspect: `g.query("CALL db.indexes()")`, `CALL db.labels()`, `CALL db.relationshipTypes()`, `g.explain(q)`, `g.profile(q)`, `g.slowlog()`
25. [T] Raise timeout cap: `docker exec fdb redis-cli GRAPH.CONFIG SET TIMEOUT_MAX 30000` (GRAPH.CONFIG GET verified; SET [U]).
26. [U] Node.js: `const {FalkorDB}=require('falkordb'); const db=await FalkorDB.connect({socket:{host:'localhost',port:6379}}); const g=db.selectGraph('x'); const r=await g.query('MATCH (n) RETURN n LIMIT 1');`
27. [U] MCP server: `FALKORDB_HOST=localhost FALKORDB_PORT=6379 npx @falkordb/mcpserver` (exact package/args per its README).

Test environment: Docker was initially not running; started Docker Desktop; container `fdb-research` removed afterwards.
