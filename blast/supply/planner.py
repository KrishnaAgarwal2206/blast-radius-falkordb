"""Remediation planner: choose, per package, the lowest installable version that clears its in-scope findings without breaking
any constraint recorded in the graph (DEPENDS_ON specifiers). Deterministic. NOT a minimum-cut solver; it is a ranked, explainable plan."""
import re
import time

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from ..analysis.core import Result, _q
from ..graph.client import run
from . import advisories, dists, net
from .apps import RUNNER_TAG


def _ver(v):
    try:
        return Version(v)
    except InvalidVersion:
        return None


def pypi_versions(name):
    """[(version, installable_on_this_python)] for stable releases, ascending."""
    info = advisories._cached(f"pypi:{name}", lambda: net.get(f"https://pypi.org/pypi/{name}/json").json())
    out = []
    for v, files in info["releases"].items():
        pv = _ver(v)
        if not pv or pv.is_prerelease or not files:
            continue
        ok = any(f["packagetype"] == "bdist_wheel" and (f["filename"].endswith("none-any.whl") and "py2-none" not in f["filename"] or re.search(rf"-{RUNNER_TAG}-", f["filename"]))
                 for f in files)
        out.append((pv, ok))
    return sorted(out)


def requires_of(name, version):
    info = advisories._cached(f"pypi:{name}:{version}", lambda: net.get(f"https://pypi.org/pypi/{name}/{version}/json").json())
    res = {}
    for r in info["info"].get("requires_dist") or []:
        if "extra ==" in r:
            continue
        m = dists.REQ_NAME.match(r)
        if m:
            res[dists.norm(m.group(1))] = r[m.end():].split(";")[0].strip().strip("()").replace(" ", "")
    return res


def plan(graph: str, findings: list[dict], pins: dict, scope=("reachable",)) -> Result:
    t0 = time.perf_counter()
    res = Result("plan_remediation")
    res.data["scope"] = list(scope)
    by_pkg = {}
    for f in findings:
        if f["verdict"] in scope:
            by_pkg.setdefault(f["package"], []).append(f)
    cands, upgrades = {}, {}

    def try_choose(pkg, fs):
        cur = _ver(pins[pkg])
        need = []
        for f in fs:
            fx = sorted((v for v in map(_ver, f["fixed"]) if v and v > cur))
            if fx:
                need.append(fx[0])
        if not need:
            return None, [], 0, None
        floor = max(need)
        # constraints recorded in the graph; a dependent that is itself being upgraded contributes its NEW specifier
        cons = []
        for d, sp in _q(res, graph, "MATCH (d:Service)-[e:DEPENDS_ON]->(p:Service {name:$p}) RETURN d.name, e.spec", {"p": pkg}).rows:
            if d in upgrades:
                sp = requires_of(d, str(upgrades[d])).get(pkg, "")
            cons.append((d, sp))
        eff = {**pins, **{k: str(v) for k, v in upgrades.items()}}
        rejected = []
        for v, installable in pypi_versions(pkg):
            if v < floor:
                continue
            bad = [f"{d} requires {pkg}{sp}" for d, sp in cons if sp and v not in SpecifierSet(sp)]
            if bad:
                rejected.append((str(v), "; ".join(bad)))
                continue
            if not installable:
                rejected.append((str(v), f"no wheel installable for the check runner (python {RUNNER_TAG} or pure-python)"))
                continue
            miss = [f"{k}{sp}" for k, sp in requires_of(pkg, str(v)).items() if k in eff and sp and _ver(eff[k]) not in SpecifierSet(sp)]
            if miss:
                rejected.append((str(v), "its dependencies not met by current pins: " + ", ".join(miss)))
                continue
            return v, rejected, len(cons), floor
        return None, rejected, len(cons), floor

    pending = dict(by_pkg)
    for _pass in range(3):          # a blocked package is retried after the packages that constrain it have been upgraded
        progress = False
        for pkg, fs in list(pending.items()):
            chosen, rejected, ncons, floor = try_choose(pkg, fs)
            if not chosen:
                cands[pkg] = dict(package=pkg, from_version=pins[pkg], to_version=None, blocked=rejected[:3], findings=[f["id"] for f in fs])
                continue
            cur = _ver(pins[pkg])
            upgrades[pkg] = chosen
            remaining = {c["id"] for c in advisories.merged(pkg, str(chosen))}
            jump = "major" if chosen.major != cur.major else "minor" if chosen.minor != cur.minor else "patch"
            cands[pkg] = dict(package=pkg, from_version=pins[pkg], to_version=str(chosen), jump=jump, floor=str(floor),
                              cleared_in_scope=[f["id"] for f in fs if f["id"] not in remaining],
                              cleared_all=[f["id"] for f in findings if f["package"] == pkg and f["id"] not in remaining],
                              remaining=sorted(remaining), constraints_checked=ncons, skipped=rejected[:3],
                              findings=[f["id"] for f in fs], path_ids=[f["path_id"] for f in fs if f.get("path_id")],
                              unblocked_by=[k for k in upgrades if k != pkg and pkg in [d for d, _ in [(k, 0)]]] if _pass else [])
            del pending[pkg]
            progress = True
        if not progress or not pending:
            break
    cands = list(cands.values())
    cands.sort(key=lambda c: (-len(c.get("cleared_in_scope", [])), {"patch": 0, "minor": 1, "major": 2}.get(c.get("jump"), 3)))
    res.data["candidates"] = cands
    res.ms = (time.perf_counter() - t0) * 1000
    return res
