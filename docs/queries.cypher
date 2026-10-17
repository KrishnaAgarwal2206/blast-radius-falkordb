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

// ================= Supply-chain mode (Reachability-to-Repair) =================
// Reachability: entry point -> function the advisory's fix commit changed (one query per advisory)
MATCH (e:Function {entry:true}),(v:Function {qname:$q})
WITH e, v, shortestPath((e)-[:CALLS*..25]->(v)) AS p WHERE p IS NOT NULL
RETURN length(p), nodes(p), relationships(p) ORDER BY length(p) LIMIT 1;

// Evidence for "no path found": what the analysis DID reach in the same file as the vulnerable function
MATCH (v:Function {qname:$q})<-[:DEFINES]-(f:File)-[:DEFINES]->(s:Function) WHERE s.qname <> $q
WITH s MATCH (e:Function {entry:true}) WITH e, s, shortestPath((e)-[:CALLS*..25]->(s)) AS p WHERE p IS NOT NULL
RETURN length(p), nodes(p) ORDER BY length(p) LIMIT 1;

// Advisories affecting pinned versions, with the functions inferred from their fix commits
MATCH (s:Service)-[a:AFFECTED_BY]->(x:Vulnerability) OPTIONAL MATCH (x)-[:VULNERABLE_IN]->(f:Function)
RETURN x.id, s.name, a.version, x.severity, x.cvss, x.fixed, collect(f.qname);

// Upgrade planning: every dependent's version specifier on a package (re-queried after an upgrade changes them)
MATCH (d:Service)-[e:DEPENDS_ON]->(p:Service {name:$p}) RETURN d.name, e.spec;

// Class hierarchy as graph structure: does this loader inherit the vulnerable constructor?
MATCH (c:Class {qname:'yaml.loader.SafeLoader'})-[:EXTENDS*1..6]->(b:Class) RETURN b.qname;

// Cross-app memory (graph sc_memory): earlier verdicts about the same advisory in other apps
MATCH (d:Decision)-[:ABOUT]->(v:Vulnerability) WHERE v.id IN $ids AND d.app <> $app
RETURN d.app, d.vuln, d.verdict, d.why ORDER BY d.ts DESC;
