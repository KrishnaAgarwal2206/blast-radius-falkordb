"""Unit tests for the supply-chain resolver, planner and scoring. No network, no real packages: a synthetic library
reproduces the patterns that matter (class-valued parameters, handler registries, partials, mixin super())."""
from pathlib import Path

import pytest

from blast.ingest import pyast
from blast.supply.analysis import cvss3_score
from blast.supply.resolve import World

LIB = '''
class Base:
    def __init__(self, stream):
        self.stream = stream

    def run(self):
        return self.dispatch("t")

    def dispatch(self, tag):
        return REGISTRY[tag]()

class Safe(Base):
    pass

class Full(Base):
    pass

def safe_handler():
    return 1

def danger_handler():
    return 2

def load(stream, Loader=None):
    loader = Loader(stream)
    return loader.run()

REGISTRY = {"safe": safe_handler, "danger": danger_handler}
'''
LIB_INIT = '''
from .core import *
'''
APP = '''
import functools
import lib
from lib import Safe, Full

DefaultLoader = getattr(lib, "Missing", Safe)

def safe_entry(path):
    return lib.load(path, Loader=Safe)

def full_entry(path):
    return lib.load(path, Loader=lib.Full)

def alias_entry(path):
    return lib.load(path, Loader=DefaultLoader)

safe_load = functools.partial(lib.load, Loader=Safe)

def partial_entry(path):
    return safe_load(path)

class Mixin:
    def go(self):
        return super().helper()

class Other:
    def helper(self):
        return lib.safe_handler()

class Combined(Mixin, Other):
    pass

def mixin_entry():
    return Combined().go()
'''


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("w")
    (d / "lib").mkdir()
    (d / "lib" / "__init__.py").write_text(LIB_INIT)
    (d / "lib" / "core.py").write_text(LIB.replace("REGISTRY = {", "REGISTRY = {"))
    (d / "app.py").write_text(APP)
    files = {}
    for rel, mod, svc in (("lib/__init__.py", "lib", "lib"), ("lib/core.py", "lib.core", "lib"), ("app.py", "app", "app")):
        fi = pyast.parse_file(d, rel, svc, module=mod, display=f"{svc}/{rel}")
        files[fi.path] = fi
    w = World(files)
    edges = dict(w.calls())
    edges.update(w.dispatch_edges())
    edges.update(w.dict_edges())
    return w, edges


def reach(edges, src, dst):
    seen, todo = {src}, [src]
    while todo:
        cur = todo.pop()
        for (a, b) in edges:
            if a == cur and b not in seen:
                seen.add(b)
                todo.append(b)
    return dst in seen


def test_star_import_and_reexport_resolve(world):
    w, _ = world
    assert w.lookup("lib.load") == ("func", "lib.core.load")


def test_class_param_dispatch_is_call_site_sensitive(world):
    w, e = world
    # both entries call the same load(); only the one that passes Full may reach the handler registered for any class
    assert ("app.safe_entry", "lib.core.Base.run") in e or reach(e, "app.safe_entry", "lib.core.Base.run")
    assert ("app.full_entry", "lib.core.Base.run") in e or reach(e, "app.full_entry", "lib.core.Base.run")


def test_alias_getattr_default_and_partial_bind_the_safe_class(world):
    w, e = world
    assert any(a == "app.alias_entry" and "param-class" in h for (a, _b), h in e.items())
    assert any(a == "app.partial_entry" and "param-class" in h and "Safe" in h for (a, _b), h in e.items())
    assert not any(a == "app.partial_entry" and "Full" in h for (a, _b), h in e.items())


def test_handler_table_reaches_every_handler_from_the_reader(world):
    _, e = world
    assert ("lib.core.Base.dispatch", "lib.core.danger_handler") in e and ("lib.core.Base.dispatch", "lib.core.safe_handler") in e


def test_mixin_super_resolves_through_subclass_mro(world):
    _, e = world
    assert ("app.Mixin.go", "app.Other.helper") in e
    assert reach(e, "app.mixin_entry", "lib.core.safe_handler")


def test_unresolvable_calls_are_not_guessed(world):
    w, e = world
    assert w.resolve_in(w.files["app/app.py"], "nothing.at.all") is None


def test_cvss3_base_score():
    assert cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == 6.1
    assert cvss3_score("garbage") is None


def test_getattr_dispatch_links_to_methods_of_live_subclasses_only(tmp_path):
    (tmp_path / "v.py").write_text('''
class Visitor:
    def visit(self, node):
        return getattr(self, "visit_" + node)(node)

class Gen(Visitor):
    def visit_A(self, n):
        return 1

class Unused(Visitor):
    def visit_B(self, n):
        return 2

def run():
    return Gen().visit("A")
''')
    fi = pyast.parse_file(tmp_path, "v.py", "app", module="v", display="app/v.py")
    w = World({fi.path: fi})
    w.calls()
    m = w.maybe_calls({"app": set()})
    assert ("v.Visitor.visit", "v.Gen.visit_A") in m
    assert ("v.Visitor.visit", "v.Unused.visit_B") not in m      # Unused is never instantiated
