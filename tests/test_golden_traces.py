"""Regression tests for stack-trace ranking (authored from real file/line numbers; expected shas verified with git log)."""
import pytest

from blast.agent import loop
from blast.graph.client import list_graphs

pytestmark = pytest.mark.skipif("otel" not in list_graphs(), reason="otel graph not ingested")
G = "otel"

SIMPLE_SPAN = '''Traceback (most recent call last):
  File "/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/trace/__init__.py", line 995, in end
    self._span_processor.on_end(self._readable_span())
  File "/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/trace/export/__init__.py", line 126, in on_end
    self.span_exporter.export((span,))
  File "/app/venv/lib/python3.12/site-packages/some_vendor_exporter/client.py", line 44, in export
    raise ConnectionError("collector unreachable")
ConnectionError: collector unreachable
'''


def _run(text):
    ev = []
    ans = loop.investigate(G, text, ev.append, use_llm=False, remember=False)
    return ans, ev


def test_failing_frame_commits_outrank_caller_commits():
    ans, _ = _run(SIMPLE_SPAN)
    causes = [c["text"] for c in ans["claims"] if c["kind"] == "cause"]
    assert causes[0].startswith("Most likely cause: 91e49a52") or "a6d59ca6" in " ".join(causes[:2])
    assert "failing file" in causes[0] or "function" in causes[0]


def test_impact_paths_end_at_the_failing_function():
    ans, ev = _run(SIMPLE_SPAN)
    imp = next(c for c in ans["claims"] if c["kind"] == "impact")
    paths = {e["path_id"]: e for e in ev if e["type"] == "path"}
    ends = {paths[p]["nodes"][-1] for p in imp["path_ids"]}
    assert len(ends) == 1 and next(iter(ends)).startswith("Function:opentelemetry.sdk.trace.export.SimpleSpanProcessor.on_end")


def test_java_trace_is_rejected_not_guessed():
    java = 'Exception in thread "main" java.lang.NullPointerException\n\tat com.acme.Foo.bar(Foo.java:42)\n\tat com.acme.Main.main(Main.java:7)'
    ans, ev = _run(java)
    assert ans is None and any("non-Python" in e.get("message", "") for e in ev if e["type"] == "error")


def test_generic_words_do_not_resolve_a_target():
    ans, ev = _run("the thread pool is stuck and the exporter looks slow")
    assert ans is None


ON_EMIT = '''Traceback (most recent call last):
  File "/app/venv/lib/python3.12/site-packages/opentelemetry/sdk/_logs/_internal/export/__init__.py", line 312, in on_emit
    self._batch_processor.emit(log_record)
RuntimeError: queue closed
'''


def test_function_level_blame_finds_the_commit_that_wrote_the_failing_lines():
    ans, _ = _run(ON_EMIT)
    cause = next(c["text"] for c in ans["claims"] if c["kind"] == "cause")
    assert cause.startswith("Most likely cause: 1d9f40b5") and "git blame" in cause   # verified: git blame -L312,312 on the pinned checkout


def test_llm_style_claims_with_unsupported_shas_are_dropped():
    r = loop.Run(G, lambda e: None)
    r.paths = {"p": dict(path_id="p", nodes=["Commit:aaaaaaaa11112222", "File:x.py"], rels=["MODIFIED"], sentence="s")}
    r.nodes = {"Commit:aaaaaaaa11112222": {}}
    out = r.finalize({"summary": "s", "confidence": 1, "claims": [
        {"kind": "cause", "text": "cause is aaaaaaaa", "path_ids": ["p"]},
        {"kind": "cause", "text": "cause is bbbbbbbb", "path_ids": ["p"]}]})
    assert [c["text"] for c in out["claims"]] == ["cause is aaaaaaaa"] and out["dropped_unverified_claims"] == 1


def test_natural_language_gets_did_you_mean_and_control_chars_are_safe():
    ans, ev = _run("who owns the metric reader")
    msgs = [e["message"] for e in ev if e["type"] == "error"]
    assert ans is None and "Did you mean" in msgs[0]
    ans, _ = _run("abc\x00def opentelemetry-sdk")
    assert ans is not None
