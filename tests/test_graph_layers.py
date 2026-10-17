from blast.analysis import core
from blast.graph import schema
from blast.graph.client import run
from blast.ingest.cli import ingest


def test_counts_and_known_edges(graph):
    s = schema.stats(graph)
    assert s["nodes"]["Service"] == 2 and s["nodes"]["File"] >= 2
    assert run(graph, "MATCH (:Service {name:'svc-b'})-[:DEPENDS_ON]->(:Service {name:'svc-a'}) RETURN count(*)").rows[0][0] == 1
    assert run(graph, "MATCH (:File {path:'svc-b/src/svc_b/api.py'})-[:IMPORTS]->(:File {path:'svc-a/src/svc_a/core.py'}) RETURN count(*)").rows[0][0] == 1
    assert run(graph, "MATCH (:Function {qname:'svc_a.core.helper'})-[:CALLS]->(:Function {qname:'svc_a.core.parse'}) RETURN count(*)").rows[0][0] == 1
    assert run(graph, "MATCH (:Function {qname:'svc_b.api.handle'})-[:CALLS]->(:Function {qname:'svc_a.core.parse'}) RETURN count(*)").rows[0][0] == 1


def test_ingest_idempotent(graph, fixture_repo):
    before = schema.stats(graph)
    ingest(str(fixture_repo), graph, months=60, log=lambda *_: None)
    assert schema.stats(graph) == before


def test_indexes_exist(graph):
    r = run(graph, "CALL db.indexes() YIELD label, properties RETURN label, properties")
    have = {(a, tuple(b)) for a, b in r.rows}
    for label, prop in schema.INDEXES:
        assert (label, (prop,)) in have


def test_blast_radius_service_and_file(graph):
    r = core.blast_radius(graph, "svc-a")
    assert [i["uid"] for i in r.data["impacted"]] == ["Service:svc-b"]
    assert r.paths[0]["sentence"] == "svc-b —DEPENDS_ON→ svc-a"
    r = core.blast_radius(graph, "svc_a/core.py")
    uids = {i["uid"] for i in r.data["impacted"]}
    assert "File:svc-b/src/svc_b/api.py" in uids and "Service:svc-b" in uids


def test_blast_radius_unknown_target(graph):
    assert "error" in core.blast_radius(graph, "does-not-exist-xyz").data


def test_function_blast_radius(graph):
    r = core.blast_radius(graph, "svc_a.core.parse")
    assert {"Function:svc_a.core.helper", "Function:svc_b.api.handle"} <= {i["uid"] for i in r.data["impacted"]}


def test_stacktrace_maps_frames(graph):
    tb = ('Traceback (most recent call last):\n  File "/app/svc_b/api.py", line 4, in handle\n'
          '    return parse(x)\n  File "/venv/lib/site-packages/svc_a/core.py", line 2, in parse\n    return int(x)\nValueError')
    r = core.trace_stacktrace(graph, tb)
    assert r.data["origin"] == "Function:svc_a.core.parse"
    assert core.trace_stacktrace(graph, "no frames here").data["error"]
    assert core.trace_stacktrace(graph, 'File "/usr/lib/python3/json/decoder.py", line 1, in x').data["error"]


def test_suspects_who_to_page_and_memory(graph):
    sus = core.suspect_changes(graph, ["File:svc-a/src/svc_a/core.py"], window_days=3650)
    assert len(sus.data["suspects"]) >= 2
    assert any(s["msg"].startswith("fix: parse") for s in sus.data["suspects"])
    page = core.who_to_page(graph, ["File:svc-a/src/svc_a/core.py"], [s["sha"] for s in sus.data["suspects"]])
    assert page.data["page"] and {p["email"] for p in page.data["page"]} <= {"alice@x.io", "bob@x.io"}
    sim = core.similar_incidents(graph, ["File:svc-a/src/svc_a/core.py"])
    assert sim.data["similar"] and "fix: parse" in sim.data["similar"][0]["title"]
    assert sim.data["similar"][0]["caused_by"]["msg"].startswith("change parse")


def test_explain_path_and_critical(graph):
    e = core.explain_path(graph, "svc-b", "svc-a")
    assert e.data["sentence"] == "svc-b —DEPENDS_ON→ svc-a"
    c = core.critical_nodes(graph, "Service")
    assert c.data["critical"][0]["uid"] == "Service:svc-a"
