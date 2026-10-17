from blast.agent import loop
from blast.graph.client import run


def test_pipeline_claims_are_path_backed_and_remembered(graph):
    ev = []
    ans = loop.investigate(graph, "svc-a", ev.append, use_llm=False, remember=True)
    assert ans and ans["claims"]
    pids = {e["path_id"] for e in ev if e["type"] == "path"}
    assert all(set(c["path_ids"]) <= pids for c in ans["claims"])
    types = [e["type"] for e in ev]
    assert types[0] == "run_started" and types[-1] == "run_finished" and "graph_query" in types
    # memory: a live incident was written, and a later run recalls it
    assert run(graph, "MATCH (i:Incident {source:'live'}) RETURN count(i)").rows[0][0] >= 1
    ans2 = loop.investigate(graph, "svc_a/core.py", lambda e: None, use_llm=False, remember=False)
    assert any(c["kind"] == "similar" for c in ans2["claims"])


def test_finalize_drops_hallucinated_claims(graph):
    r = loop.Run(graph, lambda e: None)
    r.paths = {"real": dict(path_id="real", nodes=["A:1"], rels=[], sentence="x")}
    out = r.finalize({"summary": "s", "confidence": 1, "claims": [
        {"kind": "impact", "text": "ok", "path_ids": ["real"]}, {"kind": "cause", "text": "made up", "path_ids": ["nope"]}]})
    assert len(out["claims"]) == 1 and out["dropped_unverified_claims"] == 1


def test_bad_input_is_graceful(graph):
    ev = []
    assert loop.investigate(graph, "zzz-nothing-matches-qq", ev.append, use_llm=False) is None
    assert ev[-1]["type"] == "run_finished" and any(e["type"] == "error" for e in ev)
