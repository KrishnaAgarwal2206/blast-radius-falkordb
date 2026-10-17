"""Python AST extraction: Files, Classes, Functions, IMPORTS and best-effort CALLS."""
import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileInfo:
    path: str            # repo-relative posix
    module: str          # dotted module name
    service: str
    loc: int = 0
    classes: list = field(default_factory=list)    # (qname, file)
    funcs: list = field(default_factory=list)      # dict(qname,name,start,end,cls,file)
    imports: list = field(default_factory=list)    # (kind, module, names)
    calls: list = field(default_factory=list)      # (caller_qname, call_expr, cls)
    symbols: dict = field(default_factory=dict)    # local name -> (module, attr|None)


def module_name(rel: str) -> str:
    p = rel.split("/src/", 1)[1] if "/src/" in rel else rel
    p = p[:-3]
    parts = p.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
        return ".".join(reversed(parts))
    return None


def parse_file(root: Path, rel: str, service: str) -> FileInfo | None:
    try:
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None
    mod = module_name(rel)
    fi = FileInfo(rel, mod, service, loc=src.count("\n") + 1)
    is_pkg = rel.endswith("__init__.py")
    pkg = mod if is_pkg else mod.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                fi.imports.append(("import", a.name, None))
                fi.symbols[(a.asname or a.name).split(".")[0]] = (a.name if a.asname else a.name.split(".")[0], None)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join(up + ([base] if base else []))
            names = [a.name for a in node.names]
            fi.imports.append(("from", base, names))
            for a in node.names:
                fi.symbols[a.asname or a.name] = (base, a.name)

    def visit(body, prefix, cls):
        for n in body:
            if isinstance(n, ast.ClassDef):
                q = f"{mod}.{prefix}{n.name}"
                fi.classes.append((q, rel))
                visit(n.body, f"{prefix}{n.name}.", n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{mod}.{prefix}{n.name}"
                fi.funcs.append(dict(qname=q, name=n.name, start=n.lineno, end=getattr(n, "end_lineno", n.lineno), cls=cls, file=rel))
                for c in ast.walk(n):
                    if isinstance(c, ast.Call):
                        cn = _call_name(c)
                        if cn:
                            fi.calls.append((q, cn, cls))
                visit(n.body, f"{prefix}{n.name}.", cls)

    visit(tree.body, "", None)
    return fi
