"""Thin FalkorDB wrapper: every call returns rows plus the Cypher and latency (shown in the UI)."""
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from falkordb import FalkorDB
from .. import config

_db = None


def db() -> FalkorDB:
    global _db
    if _db is None:
        _db = FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT, password=config.FALKORDB_PASSWORD)
    return _db


def list_graphs() -> list[str]:
    return db().list_graphs()


@dataclass
class QResult:
    rows: list[list[Any]]
    header: list[str]
    cypher: str
    params: dict
    ms: float          # server-side execution time
    rtt_ms: float      # client round trip
    log: list = field(default_factory=list)

    def dicts(self):
        return [dict(zip(self.header, r)) for r in self.rows]


# Observers receive every executed query (the agent streams these to the UI).
_observers: list = []
_tracker: ContextVar = ContextVar('tracker', default=None)


def track():
    """Start collecting queries in the current context; returns the list."""
    lst = []
    _tracker.set(lst)
    return lst


def observe(fn):
    _observers.append(fn)
    return lambda: _observers.remove(fn)


def run(graph: str, cypher: str, params: dict | None = None, readonly: bool = True, timeout: int = 8000) -> QResult:
    params = params or {}
    g = db().select_graph(graph)
    t0 = time.perf_counter()
    res = (g.ro_query if readonly else g.query)(cypher, params, timeout=timeout)
    rtt = (time.perf_counter() - t0) * 1000
    header = [h[1] if isinstance(h, (list, tuple)) else h for h in (res.header or [])]
    out = QResult(res.result_set, header, cypher, params, float(res.run_time_ms), rtt)
    t = _tracker.get()
    if t is not None:
        t.append(out)
    for fn in list(_observers):
        fn(out)
    return out
