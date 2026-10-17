"""Advisories from OSV + vulnerable-function inference from the advisory's FIX commit.
OSV gives affected versions and fixed versions, but not the vulnerable function. We take the functions the fix commit changed
(from the hunk headers of its diff) and look them up in the pinned source. This is an inference and is labelled as such."""
import hashlib
import json
import re

from . import net

from .. import config
from ..graph.client import run
from . import dists
from .analysis import cvss3_score, band

CACHE = config.ROOT / "data" / "envs" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
HUNK = re.compile(r"^@@ [^@]+ @@\s*(.*)$")
DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
CLS = re.compile(r"^\s*class\s+(\w+)")


def _cached(key, fn):
    p = CACHE / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")
    if p.exists():
        return json.loads(p.read_text())
    v = fn()
    p.write_text(json.dumps(v))
    return v


def osv_query(name, version):
    def go():
        r = net.post("https://api.osv.dev/v1/query", json={"package": {"name": name, "ecosystem": "PyPI"}, "version": version})
        out = r.json().get("vulns", [])
        return out
    return _cached(f"osv:{name}:{version}", go)


def fixed_versions(vuln, name):
    out = []
    for a in vuln.get("affected", []):
        if dists.norm(a.get("package", {}).get("name", "")) != dists.norm(name):
            continue
        for rg in a.get("ranges", []):
            if rg.get("type") in ("ECOSYSTEM", "SEMVER"):
                out += [e["fixed"] for e in rg.get("events", []) if "fixed" in e]
    return out


def fix_commit_urls(vuln):
    urls = []
    for r in vuln.get("references", []):
        u = r.get("url", "")
        if re.search(r"github\.com/[^/]+/[^/]+/commit/[0-9a-f]{7,40}", u):
            urls.append(re.sub(r"[#?].*$", "", u))
    for a in vuln.get("affected", []):
        for rg in a.get("ranges", []):
            if rg.get("type") == "GIT":
                repo = rg.get("repo", "")
                for e in rg.get("events", []):
                    if "fixed" in e and "github.com" in repo:
                        urls.append(f"{repo.rstrip('/').removesuffix('.git')}/commit/{e['fixed']}")
    return list(dict.fromkeys(urls))[:3]


def diff_functions(url):
    """[(path, [function names], hunk_count)] for the python files changed by a GitHub commit."""
    def go():
        r = net.get(url + ".diff")
        return r.text if r.status_code == 200 else ""
    text = _cached("diff:" + url, go)
    out, path, names = [], None, set()
    cur = None                      # name of the function enclosing the current diff line (None = module level)
    for ln in text.splitlines():
        if ln.startswith("diff --git"):
            if path:
                out.append((path, sorted(names)))
            m = re.match(r"diff --git a/(\S+) b/(\S+)", ln)
            path, names, cur = (m.group(2) if m else None), set(), None
            if path and (not path.endswith(".py") or re.search(r"(^|/)(tests?|docs?)/", path)):
                path = None
        elif path and ln.startswith("@@"):
            m = HUNK.match(ln)
            d = DEF.match(m.group(1)) if m else None
            cur = d.group(1) if d else None          # git's hunk header names the def that precedes the hunk
        elif path and ln[:1] in "+- " and not ln.startswith(("+++", "---")):
            body = ln[1:]
            d = DEF.match(body)
            if d:
                cur = d.group(1)
            elif body[:1].isalpha() and not body.startswith(("def ", "async ", "class ")) and not body.startswith((")", "]", "}")):
                cur = None                           # unindented module-level statement ends the function
            if ln[0] in "+-" and cur:
                names.add(cur)
            elif ln[0] == "-" and cur is None:
                # module-level change (e.g. a handler registration removed): the functions it referenced as Class.handler are the affected code
                names.update(re.findall(r"\b[A-Z]\w*\.(\w+)\b(?!\s*\()", body))
    if path:
        out.append((path, sorted(names)))
    return [(p, n) for p, n in out if n]


def merged(name, version):
    """OSV often has two records for one CVE (GHSA + PYSEC). Merge them by CVE id."""
    groups = {}
    for v in osv_query(name, version):
        cve = next((a for a in v.get("aliases", []) + [v["id"]] if a.startswith("CVE-")), v["id"])
        g = groups.setdefault(cve, dict(id=cve, osv=[], aliases=set(), severity=[], sev_label=None, summary="", fixed=set(), urls=[]))
        g["osv"].append(v["id"])
        g["aliases"] |= set(v.get("aliases", [])) | {v["id"]}
        g["severity"] += v.get("severity", [])
        g["sev_label"] = g["sev_label"] or (v.get("database_specific") or {}).get("severity")
        g["summary"] = g["summary"] or (v.get("summary") or "")
        g["fixed"] |= set(fixed_versions(v, name))
        g["urls"] += fix_commit_urls(v)
    for g in groups.values():
        g["urls"] = list(dict.fromkeys(g["urls"]))[:3]
    return list(groups.values())


def ingest_advisories(graph: str, pins: dict, log=print):
    """Query OSV for every pinned dist, map vulnerable functions, write Vulnerability nodes + edges."""
    total, mapped = 0, 0
    for name, ver in pins.items():
        for g in merged(name, ver):
            total += 1
            cve = g["id"]
            cv = next((cvss3_score(x["score"]) for x in g["severity"] if x.get("type") == "CVSS_V3" and x["score"].startswith("CVSS:3")), None)
            sev = g["sev_label"] or band(cv)
            fixed = sorted(g["fixed"], key=lambda x: [int(p) if p.isdigit() else 0 for p in re.split(r"[.]", x)])
            run(graph, "MERGE (x:Vulnerability {id:$id}) SET x.osv=$osv, x.aliases=$al, x.severity=$sev, x.cvss=$cvss, x.summary=$sum, x.fixed=$fx, x.package=$pk "
                       "WITH x MATCH (s:Service {name:$pk}) MERGE (s)-[e:AFFECTED_BY]->(x) SET e.version=$ver",
                {"id": cve, "cvss": cv, "osv": g["osv"], "al": sorted(g["aliases"]), "sev": sev, "sum": g["summary"][:200], "fx": fixed, "pk": name, "ver": ver},
                readonly=False)
            fns = []
            for url in g["urls"]:
                for path, names in diff_functions(url):
                    suffix = "/".join(path.split("/")[-2:])
                    r = run(graph, "MATCH (f:File {service:$s})-[:DEFINES]->(fn:Function) WHERE f.path ENDS WITH $suf AND fn.name IN $names RETURN fn.qname",
                            {"s": name, "suf": suffix, "names": names})
                    for (q,) in r.rows:
                        fns.append((q, url, path))
            fns = list(dict.fromkeys(fns))
            if 0 < len(fns) <= 8:
                mapped += 1
                for q, url, path in fns:
                    run(graph, "MATCH (x:Vulnerability {id:$id}) MATCH (fn:Function {qname:$q}) MERGE (x)-[e:VULNERABLE_IN]->(fn) SET e.source='fix-diff', e.commit=$u, e.file=$p",
                        {"id": cve, "q": q, "u": url, "p": path}, readonly=False)
                run(graph, "MATCH (x:Vulnerability {id:$id}) SET x.mapping='fix-diff'", {"id": cve}, readonly=False)
            else:
                run(graph, "MATCH (x:Vulnerability {id:$id}) SET x.mapping=$m", {"id": cve, "m": "ambiguous" if fns else "none"}, readonly=False)
    log(f"{total} advisories, {mapped} with a vulnerable function inferred from the fix commit")
    return total, mapped
