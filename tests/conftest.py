import subprocess

import pytest

from blast.graph.client import db
from blast.ingest.cli import ingest

TEST_GRAPH = "blast_test_fixture"


def _git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory):
    """Tiny two-service repo: svc-b depends on svc-a; real commits incl. a fix with a known cause."""
    d = tmp_path_factory.mktemp("fixrepo")
    _git(d, "init", "-q")
    _git(d, "config", "user.name", "Alice")
    _git(d, "config", "user.email", "alice@x.io")
    for name, deps in (("svc-a", ""), ("svc-b", '"svc-a"')):
        p = d / name
        (p / "src" / name.replace("-", "_")).mkdir(parents=True)
        (p / "pyproject.toml").write_text(f'[project]\nname="{name}"\ndependencies=[{deps}]\n')
        (p / "src" / name.replace("-", "_") / "__init__.py").write_text("")
    a = d / "svc-a/src/svc_a"
    b = d / "svc-b/src/svc_b"
    (a / "core.py").write_text("def parse(x):\n    return int(x)\n\ndef helper():\n    return parse('1')\n")
    (b / "api.py").write_text("from svc_a.core import parse\n\ndef handle(x):\n    return parse(x)\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "initial import")
    (a / "core.py").write_text("def parse(x):\n    return int(x) * 2\n\ndef helper():\n    return parse('1')\n")
    _git(d, "commit", "-qam", "change parse to double values")
    _git(d, "config", "user.name", "Bob")
    _git(d, "config", "user.email", "bob@x.io")
    (a / "core.py").write_text("def parse(x):\n    return int(x)\n\ndef helper():\n    return parse('1')\n")
    _git(d, "commit", "-qam", "fix: parse should not double values")
    return d


@pytest.fixture(scope="session")
def graph(fixture_repo):
    try:
        db().select_graph(TEST_GRAPH).delete()
    except Exception:
        pass
    ingest(str(fixture_repo), TEST_GRAPH, months=60, log=lambda *_: None)
    yield TEST_GRAPH
    try:
        db().select_graph(TEST_GRAPH).delete()
    except Exception:
        pass
