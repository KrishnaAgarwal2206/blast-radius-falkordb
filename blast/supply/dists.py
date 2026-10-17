"""Resolve a pinned environment WITHOUT building anything: fetch each pinned distribution's wheel (or sdist) from PyPI,
extract only the .py files, and read its declared dependencies. Used so the graph can contain the real third-party code."""
import io
import re
import tarfile
import zipfile
from pathlib import Path

from . import net

from .. import config

ENV_DIR = config.ROOT / "data" / "envs"
SKIP = re.compile(r"(^|/)(tests?|testing|docs?|examples?|benchmarks?|scripts?|\.github|__pycache__)(/|$)|(^|/)(setup|conftest)\.py$")
REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)")


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def parse_pins(text: str):
    pins = {}
    for ln in text.splitlines():
        ln = ln.split("#")[0].strip()
        m = re.match(r"^([A-Za-z0-9._\-]+)==([\w.\-+]+)$", ln)
        if m:
            pins[norm(m.group(1))] = m.group(2)
    return pins


def _pick(urls):
    wheels = [u for u in urls if u["packagetype"] == "bdist_wheel"]
    pure = [u for u in wheels if u["filename"].endswith("none-any.whl") and "py2-none" not in u["filename"]]
    py3 = [u for u in wheels if re.search(r"-cp3\d+-", u["filename"])]
    for group in (pure, py3):
        if group:
            return group[0]
    sd = [u for u in urls if u["packagetype"] == "sdist"]
    return sd[0] if sd else None


def _module_of(path: Path, top: Path) -> str:
    parts = [path.stem]
    d = path.parent
    while d != top and (d / "__init__.py").exists():
        parts.insert(0, d.name)
        d = d.parent
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def fetch(name: str, version: str, force=False) -> dict:
    """Download + extract .py of one pinned distribution. Returns dict(name, version, root, requires, files{rel: module})."""
    root = ENV_DIR / "src" / f"{norm(name)}-{version}"
    meta_f = root / "_meta.json"
    if meta_f.exists() and not force:
        import json
        return json.loads(meta_f.read_text())
    info = net.get(f"https://pypi.org/pypi/{name}/{version}/json").json()
    pick = _pick(info["urls"])
    if not pick:
        raise RuntimeError(f"no downloadable artifact for {name}=={version}")
    blob = net.get(pick["url"]).content
    root.mkdir(parents=True, exist_ok=True)
    if pick["packagetype"] == "bdist_wheel":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                if n.endswith(".py") and not SKIP.search(n):
                    z.extract(n, root)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as t:
            for m in t.getmembers():
                if m.isfile() and m.name.endswith(".py") and not SKIP.search(m.name):
                    t.extract(m, root, filter="data")
    files = {}
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if SKIP.search(rel) or ".dist-info" in rel or ".egg-info" in rel:
            continue
        files[rel] = _module_of(p, root)
    if any("/lib3/" in r for r in files):          # sdists that ship both python2 (lib/) and python3 (lib3/) trees
        files = {r: m for r, m in files.items() if "/lib/" not in r}
    requires = {}
    for r in info["info"].get("requires_dist") or []:
        if "extra ==" in r:
            continue
        m = REQ_NAME.match(r)
        if m:
            spec = r[m.end():].split(";")[0].strip().strip("()").replace(" ", "")
            requires[norm(m.group(1))] = spec
    meta = dict(name=norm(name), version=version, root=str(root), requires=requires, files=files, artifact=pick["filename"])
    import json
    meta_f.write_text(json.dumps(meta))
    return meta
