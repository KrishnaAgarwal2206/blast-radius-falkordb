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
    classes: list = field(default_factory=list)    # (qname, file, bases[list of expr str])
    funcs: list = field(default_factory=list)      # dict(qname,name,start,end,cls,file)
    imports: list = field(default_factory=list)    # (kind, module, names)
    calls: list = field(default_factory=list)      # (caller_qname, call_expr, cls)
    symbols: dict = field(default_factory=dict)    # local name -> (module, attr|None)
    callargs: list = field(default_factory=list)   # (caller_qname, call_expr, [(position|keyword, arg_expr)])
    partials: dict = field(default_factory=dict)   # NAME = functools.partial(F, k=v): name -> (F expr, [(key, expr)])
    stars: list = field(default_factory=list)      # `from X import *` bases
    aliases: dict = field(default_factory=dict)    # module-level NAME = <expr>: candidate dotted exprs (class-valued aliases)


def module_name(rel: str) -> str:
    p = rel.split("/src/", 1)[1] if "/src/" in rel else rel
    p = p[:-3]
    parts = p.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _expr_name(f) -> str | None:
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
        return ".".join(reversed(parts))
    if isinstance(f, ast.Call) and isinstance(f.func, ast.Name) and f.func.id == "super":
        parts.append("super()")
        return ".".join(reversed(parts))
    return None


def _call_name(node: ast.Call) -> str | None:
    return _expr_name(node.func)


def parse_file(root: Path, rel: str, service: str, module: str | None = None, display: str | None = None) -> FileInfo | None:
    try:
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None
    mod = module if module is not None else module_name(rel)
    fi = FileInfo(display or rel, mod, service, loc=src.count("\n") + 1)
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
                if a.name == "*":
                    fi.stars.append(base)
                else:
                    fi.symbols[a.asname or a.name] = (base, a.name)

    def visit(body, prefix, cls):
        for n in body:
            if isinstance(n, ast.ClassDef):
                q = f"{mod}.{prefix}{n.name}"
                fi.classes.append((q, display or rel, [b for b in (_expr_name(x) for x in n.bases) if b]))
                visit(n.body, f"{prefix}{n.name}.", n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{mod}.{prefix}{n.name}"
                vartypes = {}
                for c in ast.walk(n):   # tiny local type inference: x = Cls(...)  /  with Cls(...) as x
                    if isinstance(c, ast.Assign) and isinstance(c.value, ast.Call) and len(c.targets) == 1 and isinstance(c.targets[0], ast.Name):
                        t = _call_name(c.value)
                        if t:
                            vartypes[c.targets[0].id] = t
                    elif isinstance(c, ast.With):
                        for it in c.items:
                            if isinstance(it.context_expr, ast.Call) and isinstance(it.optional_vars, ast.Name):
                                t = _call_name(it.context_expr)
                                if t:
                                    vartypes[it.optional_vars.id] = t
                rettype = None
                for c in ast.walk(n):
                    if isinstance(c, ast.Return) and c.value is not None:
                        if isinstance(c.value, ast.Name) and c.value.id in vartypes:
                            rettype = vartypes[c.value.id]
                        elif isinstance(c.value, ast.Call):
                            rettype = _call_name(c.value)
                        if rettype:
                            break
                decos = [d for d in (_expr_name(x.func if isinstance(x, ast.Call) else x) for x in n.decorator_list) if d]
                fi.funcs.append(dict(qname=q, name=n.name, start=n.lineno, end=getattr(n, "end_lineno", n.lineno), cls=cls, file=display or rel,
                                     decorators=decos, vartypes=vartypes, rettype=rettype, params=[a.arg for a in n.args.args + n.args.kwonlyargs]))
                for c in ast.walk(n):
                    if isinstance(c, ast.Call):
                        cn = _call_name(c)
                        if cn:
                            fi.calls.append((q, cn, cls))
                            ca = [(i, _expr_name(a)) for i, a in enumerate(c.args) if _expr_name(a)]
                            ca += [(k.arg, _expr_name(k.value)) for k in c.keywords if k.arg and _expr_name(k.value)]
                            if ca:
                                fi.callargs.append((q, cn, ca))
                visit(n.body, f"{prefix}{n.name}.", cls)

    visit(tree.body, "", None)
    for n in tree.body:   # module-level registrations such as  Cls.add_constructor(tag, Cls.handler)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            cn = _call_name(n.value)
            ca = [(i, _expr_name(a)) for i, a in enumerate(n.value.args) if _expr_name(a)]
            ca += [(k.arg, _expr_name(k.value)) for k in n.value.keywords if k.arg and _expr_name(k.value)]
            if cn and ca:
                fi.callargs.append((f"<module>:{mod}", cn, ca))
    for n in tree.body:   # module-level partials
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Call):
            if (_call_name(n.value) or "").split(".")[-1] == "partial" and n.value.args and _expr_name(n.value.args[0]):
                kw = [(k.arg, _expr_name(k.value)) for k in n.value.keywords if k.arg and _expr_name(k.value)]
                fi.partials[n.targets[0].id] = (_expr_name(n.value.args[0]), kw)
    for n in tree.body:   # module-level aliases such as  Loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            cands = []
            for sub in ast.walk(n.value):
                if isinstance(sub, ast.Call) and _expr_name(sub.func) == "getattr" and len(sub.args) >= 2 and isinstance(sub.args[1], ast.Constant):
                    base = _expr_name(sub.args[0])
                    if base and isinstance(sub.args[1].value, str):
                        cands.append(f"{base}.{sub.args[1].value}")
                elif isinstance(sub, (ast.Attribute, ast.Name)):
                    e = _expr_name(sub)
                    if e:
                        cands.append(e)
            if cands:
                fi.aliases[n.targets[0].id] = list(dict.fromkeys(cands))
    return fi
