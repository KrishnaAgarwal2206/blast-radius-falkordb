import pytest

from blast.agent import guard


@pytest.mark.parametrize("q", [
    "CREATE (n:X)", "MATCH (n) DELETE n", "MATCH (n) SET n.a=1", "MATCH (n) RETURN n; MATCH (m) RETURN m",
    "CALL db.labels()", "DROP INDEX x", "MATCH (n) DETACH DELETE n", "LOAD CSV FROM 'x' AS r RETURN r", "", "FOO BAR",
    "MATCH (n) MERGE (m:X) RETURN n",
])
def test_rejects(q):
    with pytest.raises(guard.GuardError):
        guard.check(q)


def test_adds_and_caps_limit():
    assert guard.check("MATCH (n) RETURN n").endswith("LIMIT 100")
    assert "LIMIT 200" in guard.check("MATCH (n) RETURN n LIMIT 99999")
    assert guard.check("MATCH (n) RETURN n LIMIT 5").endswith("LIMIT 5")


def test_allows_algo_and_ignores_keywords_in_strings():
    assert guard.check("CALL algo.pageRank('Service','DEPENDS_ON') YIELD node, score RETURN node.name")
    assert guard.check("MATCH (n:Commit) WHERE n.msg CONTAINS 'SET value; CREATE' RETURN n.sha")
