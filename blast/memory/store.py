"""L5 memory: the graph is the memory. Investigations are persisted as Incident nodes."""
import time

from ..analysis.core import Result, uid
from ..graph.client import run


def record_incident(graph: str, args: dict) -> Result:
    """args: title, files[], services[], cause_sha?, resolved_by_email?, similar_ids[]"""
    res = Result("record_incident")
    iid = args.get("id") or f"live-{int(time.time())}"
    title = (args.get("title") or "Investigated incident")[:200]
    r = run(graph, "MERGE (i:Incident {id:$id}) SET i.title=$t, i.ts=$ts, i.source='live'",
            {"id": iid, "t": title, "ts": int(time.time())}, readonly=False)
    res.queries.append(r)
    for label, key, ids in (("File", "path", args.get("files", [])[:12]), ("Service", "name", args.get("services", [])[:6])):
        if ids:
            res.queries.append(run(graph, f"UNWIND $k AS k MATCH (i:Incident {{id:$id}}) MATCH (t:{label} {{{key}:k}}) "
                                          f"MERGE (i)-[:AFFECTED]->(t)", {"id": iid, "k": ids}, readonly=False))
    if args.get("cause_sha"):
        res.queries.append(run(graph, "MATCH (i:Incident {id:$id}) MATCH (c:Commit {sha:$s}) MERGE (i)-[e:CAUSED_BY]->(c) SET e.confidence=0.5",
                               {"id": iid, "s": args["cause_sha"]}, readonly=False))
    if args.get("resolved_by_email"):
        res.queries.append(run(graph, "MATCH (i:Incident {id:$id}) MATCH (p:Person {email:$e}) MERGE (i)-[:RESOLVED_BY]->(p)",
                               {"id": iid, "e": args["resolved_by_email"]}, readonly=False))
    if args.get("similar_ids"):
        res.queries.append(run(graph, "UNWIND $k AS k MATCH (i:Incident {id:$id}) MATCH (o:Incident {id:k}) MERGE (i)-[:SIMILAR_TO]->(o)",
                               {"id": iid, "k": args["similar_ids"]}, readonly=False))
    res.data = {"recorded": uid("Incident", iid), "id": iid}
    res.nodes[uid("Incident", iid)] = dict(label="Incident", key=iid, name=title)
    return res
