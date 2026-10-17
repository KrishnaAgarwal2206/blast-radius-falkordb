"""Golden tests against the real OpenTelemetry graph (skipped if it has not been ingested)."""
import pytest

from blast.analysis import core
from blast.graph.client import list_graphs, run

pytestmark = pytest.mark.skipif("otel" not in list_graphs(), reason="otel graph not ingested")
G = "otel"


def _files(svc):
    return ["File:" + r[0] for r in run(G, "MATCH (f:File {service:$s}) RETURN f.path", {"s": svc}).rows]


def test_scenario1_service_down():
    br = core.blast_radius(G, "opentelemetry-exporter-otlp-proto-grpc")
    assert "Service:opentelemetry-exporter-otlp" in {i["uid"] for i in br.data["impacted"]}
    sus = core.suspect_changes(G, _files("opentelemetry-exporter-otlp-proto-grpc"), window_days=120)
    assert {"f36c1288", "8acde049"} <= {s["sha"][:8] for s in sus.data["suspects"]}
    page = core.who_to_page(G, ["Service:opentelemetry-exporter-otlp-proto-grpc"], [s["sha"] for s in sus.data["suspects"]])
    assert page.data["page"]


def test_scenario2_change_impact():
    f = "opentelemetry-sdk/src/opentelemetry/sdk/metrics/_internal/view.py"
    br = core.blast_radius(G, f)
    uids = {i["uid"] for i in br.data["impacted"]}
    assert "Service:opentelemetry-exporter-otlp-proto-grpc" in uids
    assert any(u.endswith("_view_instrument_match.py") for u in uids)
    assert core.similar_incidents(G, ["File:" + f]).data["similar"]


def test_scenario3_stacktrace():
    tb = ('Traceback (most recent call last):\n  File "/v/site-packages/opentelemetry/sdk/metrics/_internal/export/__init__.py", '
          'line 520, in _receive_metrics\n    x\nTimeoutError')
    r = core.trace_stacktrace(G, tb)
    assert r.data["origin"].startswith("Function:opentelemetry.sdk.metrics._internal.export.")


def test_critical_nodes_sane():
    assert core.critical_nodes(G, "Service").data["critical"][0]["uid"] == "Service:opentelemetry-api"
