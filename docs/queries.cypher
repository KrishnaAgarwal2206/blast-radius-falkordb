// Representative FalkorDB queries / algorithms Blast Radius depends on (all parameterized in code; see blast/analysis/core.py)

// Bulk load (batched, idempotent)
UNWIND $rows AS r MATCH (s:Service {name:r.service}) MERGE (f:File {path:r.path}) SET f.loc=r.loc MERGE (s)-[:CONTAINS]->(f);
CREATE INDEX FOR (n:File) ON (n.path);

// Blast radius of a file: reverse IMPORTS closure, then dependent services (multi-hop, returns the paths)
MATCH p=(x:File)-[:IMPORTS*1..3]->(t:File {path:$k}) RETURN nodes(p), relationships(p) LIMIT 400;
MATCH p=(x:Service)-[:DEPENDS_ON*1..3]->(t:Service {name:$k}) RETURN nodes(p), relationships(p) LIMIT 200;

// Stack frame -> Function (interval containment on indexed File)
MATCH (f:File {path:$p})-[:DEFINES]->(fn:Function) WHERE fn.start <= $l AND fn.end >= $l RETURN fn.qname ORDER BY fn.end - fn.start LIMIT 1;

// Suspect commits: recent changes to the failing function/file or what it imports
MATCH p=(c:Commit)-[m:MODIFIED]->(t:File) WHERE t.path IN $k AND c.ts >= $since RETURN c.sha, c.msg, c.ts, m.adds, m.dels, nodes(p), relationships(p);

// Who to page: inferred ownership + authors of suspect commits
MATCH p=(x:Person)-[o:OWNS]->(t:Service) WHERE t.name IN $k AND coalesce(x.bot,false)=false RETURN x.email, x.name, o.score, nodes(p), relationships(p);

// Memory: past incidents on the same files, with cause and fix
MATCH p=(i:Incident)-[:AFFECTED]->(f:File) WHERE f.path IN $k RETURN i.id, i.title, f.path;
MATCH p=(i:Incident {id:$i})-[:CAUSED_BY]->(c:Commit) RETURN c.sha, c.msg, nodes(p), relationships(p);

// Shortest path between two nodes
MATCH (a:Service {name:$a}),(b:Service {name:$b}) WITH shortestPath((a)-[:IMPORTS|CALLS|DEPENDS_ON|DEFINES|CONTAINS*..6]->(b)) AS p WHERE p IS NOT NULL RETURN nodes(p), relationships(p);

// Native algorithms
CALL algo.pageRank('Service','DEPENDS_ON') YIELD node, score RETURN node.name, score ORDER BY score DESC LIMIT 8;
CALL algo.betweenness({nodeLabels:['Service'], relationshipTypes:['DEPENDS_ON']}) YIELD node, score RETURN node.name, score;
CALL algo.labelPropagation({nodeLabels:['Service'], relationshipTypes:['DEPENDS_ON']}) YIELD node, communityId RETURN node.name, communityId;
