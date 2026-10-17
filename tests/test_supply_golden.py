"""Golden tests on the real supply-chain graphs (skipped when they have not been built: python -m blast.supply.pipeline <app>),
plus a planner test on a synthetic graph."""
import pytest
from packaging.version import Version

from blast.agent import loop
from blast.graph.client import db, list_graphs, run
from blast.supply import advisories, planner
from blast.supply.analysis import verdicts

have = lambda g: g in list_graphs()


def _finding(graph, vuln):
    return next(f for f in verdicts(graph).data["findings"] if f["id"] == vuln)


@pytest.mark.skipif(not have("sc_httpie"), reason="sc_httpie not built")
def test_httpie_requests_cve_is_reachable_through_session_send():
    r = verdicts("sc_httpie")
    f = next(x for x in r.data["findings"] if x["id"] == "CVE-2023-32681")
    assert f["verdict"] == "reachable" and f["hops"] <= 5 and f["target"].endswith("rebuild_proxies")
    sentence = next(p["sentence"] for p in r.paths if p["path_id"] == f["path_id"])
    assert "Session.send" in sentence and sentence.split(" —")[0].endswith("main")     # starts at an entry point
    assert sum(r.data["counts"].values()) == r.data["total"] == len(r.data["findings"])


@pytest.mark.skipif(not (have("sc_precommit") and have("sc_yamlfull")), reason="pyyaml control apps not built")
def test_same_critical_cve_has_different_verdicts_in_two_apps():
    safe, full = _finding("sc_precommit", "CVE-2020-14343"), _finding("sc_yamlfull", "CVE-2020-14343")
    assert safe["package"] == full["package"] == "pyyaml" and safe["version"] == full["version"] == "5.3.1"
    assert full["verdict"] == "reachable" and safe["verdict"] == "no_path_found"
    assert safe.get("sibling_path_id")            # evidence of what the analysis DID reach in the same file


@pytest.mark.skipif(not (have("sc_precommit") and have("sc_memory")), reason="not built")
def test_supply_answer_is_path_backed_never_claims_not_exploitable_and_recalls_other_app():
    ev = []
    ans = loop.investigate("sc_yamlfull", "triage", ev.append, use_llm=False, remember=False)
    assert ans["dropped_unverified_claims"] == 0 and ans["claims"] and ans["actions"]
    paths = {e["path_id"] for e in ev if e["type"] == "path"}
    assert all(set(c["path_ids"]) <= paths for c in ans["claims"] + ans["actions"])
    assert any(c["kind"] == "memory" and "precommit" in c["text"] for c in ans["claims"])
    ans2 = loop.investigate("sc_precommit", "triage", lambda e: None, use_llm=False, remember=False)
    nop = [c for c in ans2["claims"] if c["kind"] == "similar"]
    assert nop and all("not a proof of non-exploitability" in c["text"] for c in nop)
    assert not any("not exploitable" in c["text"].lower().replace("not a proof of non-exploitability", "") for c in ans2["claims"])


@pytest.mark.skipif(not have("sc_httpie"), reason="not built")
def test_remediation_plan_is_ordered_by_graph_constraints_and_failed_checks_are_reported():
    ev = []
    ans = loop.investigate("sc_httpie", "triage", ev.append, use_llm=False, remember=False)
    text = " ".join(c["text"] for c in ans["claims"])
    assert "requests 2.26.0 -> 2.32" in text and "smoke checks PASS" in text
    assert "urllib3 1.26.7 -> 2." in text and "smoke checks FAIL" in text      # the fix that breaks the app is not offered as safe
    titles = [a["title"] for a in ans["actions"]]
    assert any(t.startswith("Pin requests==") for t in titles) and any(t.startswith("Do NOT pin urllib3") for t in titles)
    assert all(a["verified"] for a in ans["actions"])


def test_planner_unblocks_a_package_after_its_dependent_is_upgraded(monkeypatch):
    g = "blast_test_plan"
    try:
        db().select_graph(g).delete()
    except Exception:
        pass
    run(g, "CREATE (:Service {name:'app'})-[:DEPENDS_ON {spec:'>=1'}]->(:Service {name:'a', version:'1.0'}), "
           "(:Service {name:'a'})-[:DEPENDS_ON {spec:'<2'}]->(:Service {name:'b', version:'1.0'})", readonly=False)
    run(g, "MATCH (a:Service {name:'a'}), (b:Service {name:'b'}) WHERE a.version = '1.0' MERGE (a)-[:DEPENDS_ON {spec:'<2'}]->(b)", readonly=False)
    vers = {"a": ["1.0", "1.5"], "b": ["1.0", "2.0"]}
    monkeypatch.setattr(planner, "pypi_versions", lambda n: [(Version(v), True) for v in vers[n]])
    reqs = {("a", "1.0"): {"b": "<2"}, ("a", "1.5"): {"b": "<3"}, ("b", "2.0"): {}}
    monkeypatch.setattr(planner, "requires_of", lambda n, v: reqs.get((n, v), {}))
    monkeypatch.setattr(advisories, "merged", lambda n, v: [])
    findings = [dict(id="CVE-X", package="a", version="1.0", fixed=["1.5"], verdict="reachable", path_id="p1"),
                dict(id="CVE-Y", package="b", version="1.0", fixed=["2.0"], verdict="reachable", path_id="p2")]
    res = planner.plan(g, findings, {"a": "1.0", "b": "1.0"})
    got = {c["package"]: c["to_version"] for c in res.data["candidates"]}
    assert got == {"a": "1.5", "b": "2.0"}              # b is blocked by a<2 until a is upgraded to a version that allows b 2.x
    db().select_graph(g).delete()


@pytest.mark.skipif(not have("sc_cookiecutter"), reason="sc_cookiecutter not built")
def test_getattr_visitor_dispatch_is_unknown_not_no_path_and_unused_classes_are_not_linked():
    f = _finding("sc_cookiecutter", "CVE-2024-56201")       # CodeGenerator.visit_FromImport, called through getattr(self, 'visit_' + ...)
    assert f["verdict"] == "unknown" and f.get("reason") == "possible_via_dynamic_dispatch"
    g = _finding("sc_cookiecutter", "CVE-2024-56326")       # SandboxedEnvironment: never instantiated by the app
    assert g["verdict"] != "reachable" and not g.get("possible_path_id")


@pytest.mark.skipif(not (have("sc_httpie") and have("sc_httpie__up_urllib3")), reason="upgraded graph not built")
def test_graph_preflight_predicts_the_urllib3_break_before_any_test_runs():
    from blast.supply import agent as sa
    pre = {x["package"]: x for x in sa.t_preflight("sc_httpie", {}).data["preflight"]}
    assert pre["urllib3"]["n_missing"] >= 1 and any(m["name"] == "DEFAULT_CIPHERS" for m in pre["urllib3"]["missing"])
    assert pre["requests"]["n_missing"] == 0


@pytest.mark.skipif(not have("sc_httpie"), reason="not built")
def test_cve_input_focuses_the_answer_and_unknown_cve_is_rejected():
    ans = loop.investigate("sc_httpie", "what about CVE-2023-32681?", lambda e: None, use_llm=False, remember=False)
    assert ans["summary"].startswith("Focus CVE-2023-32681")
    assert all("CVE-2023-32681" in c["text"] or "requests" in c["text"] for c in ans["claims"])
    assert not any("urllib3" in c["text"] for c in ans["claims"])
    ev = []
    assert loop.investigate("sc_httpie", "CVE-1999-0001", ev.append, use_llm=False, remember=False) is None
    assert any("not among" in e.get("message", "") for e in ev if e["type"] == "error")


@pytest.mark.skipif(not (have("sc_yamlfull") and have("sc_memory")), reason="not built")
def test_memory_claims_only_appear_when_the_earlier_verdict_differs():
    for g in ("sc_yamlfull", "sc_httpie", "sc_cookiecutter"):
        ans = loop.investigate(g, "triage", lambda e: None, use_llm=False, remember=False)
        for c in ans["claims"]:
            if c["kind"] == "memory":
                assert "was previously assessed" in c["text"] and c["text"].count("'reachable'") < 2


@pytest.mark.skipif(not have("sc_httpie"), reason="not built")
def test_plan_outcome_is_recomputed_on_the_upgraded_graph():
    import json
    from blast.supply import pipeline as P
    snap = P.load("httpie")
    assert snap["after"]["counts"]["reachable"] < snap["counts"]["reachable"]          # applying the passing upgrade removes reachable advisories
    assert any(x["id"] == "CVE-2025-50181" for x in snap["after"]["reachable"])         # ...and the one that needs an app change is still listed
    ans = loop.investigate("sc_httpie", "triage", lambda e: None, use_llm=False, remember=False)
    assert any(c["text"].startswith("Plan outcome") for c in ans["claims"])
