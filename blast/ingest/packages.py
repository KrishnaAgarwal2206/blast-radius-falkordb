"""Services = in-repo packages (dirs with pyproject.toml + src/); Packages = external deps."""
import re
import tomllib
from pathlib import Path

DEP_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def norm(n: str) -> str:
    return n.lower().replace("_", "-")


def discover_services(root: Path):
    """Return list of dict(name, path, deps)."""
    out = []
    for pp in sorted(root.rglob("pyproject.toml")):
        rel = pp.parent.relative_to(root).as_posix()
        if rel in (".", "") or any(x in rel for x in ("node_modules", ".tox", "docs", "codegen", "scripts")):
            continue
        if not (pp.parent / "src").exists():
            continue
        try:
            data = tomllib.loads(pp.read_text(encoding="utf-8"))
        except Exception:
            continue
        proj = data.get("project", {})
        name = norm(proj.get("name") or pp.parent.name)
        deps = []
        for d in proj.get("dependencies", []):
            m = DEP_NAME.match(d)
            if m:
                deps.append(norm(m.group(1)))
        out.append(dict(name=name, path=rel, deps=deps))
    return out
