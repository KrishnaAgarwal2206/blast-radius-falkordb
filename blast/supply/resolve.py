"""Cross-package call resolution over the app + its pinned third-party code.
Static and best effort: follows imports and re-exports, class inheritance, self/super calls, constructor calls,
local `x = Cls()` types and simple return types. Anything it cannot resolve stays unresolved (never guessed)."""
import re


class World:
    def __init__(self, files: dict):
        self.files = files
        self.funcs = {fn["qname"]: fn for f in files.values() for fn in f.funcs}
        self.classes = {q: dict(file=fp, bases=bases, resolved=[]) for f in files.values() for q, fp, bases in f.classes}
        self.modules = {f.module: f for f in files.values()}
        self.by_path = files
        self.partials = {f"{fi.module}.{n}": (fi, fe, kw) for fi in files.values() for n, (fe, kw) in fi.partials.items()}
        self.file_of = {fn["qname"]: files[fn["file"]] for fn in self.funcs.values() if fn["file"] in files}
        for q, c in self.classes.items():
            fi = files.get(c["file"])
            for b in c["bases"]:
                r = self.resolve_in(fi, b) if fi else None
                if r and r[0] == "class":
                    c["resolved"].append(r[1])

    # ---- name lookup
    def lookup(self, q, depth=0):
        if depth > 6:
            return None
        if q in self.partials:                                          # functools.partial alias: calls go to the wrapped function
            fi, fe, _kw = self.partials[q]
            return self.resolve_in(fi, fe, depth=depth + 1)
        if q in self.funcs:
            return ("func", q)
        if q in self.classes:
            return ("class", q)
        if q in self.modules:
            return ("module", q)
        m, _, n = q.rpartition(".")
        if not m:
            return None
        if m in self.modules and n in self.modules[m].symbols:       # re-export through a module's imports
            base, attr = self.modules[m].symbols[n]
            return self.lookup(f"{base}.{attr}" if attr else base, depth + 1)
        if m in self.modules:                                           # names pulled in by `from X import *`
            for sb in self.modules[m].stars:
                r = self.lookup(f"{sb}.{n}", depth + 1)
                if r:
                    return r
        r = self.lookup(m, depth + 1)
        if r and r[0] == "class":
            f = self.find_method(r[1], n)
            return ("func", f) if f else None
        return None

    def find_method(self, cls_q, name, seen=None):
        seen = seen or set()
        if cls_q in seen or cls_q not in self.classes:
            return None
        seen.add(cls_q)
        q = f"{cls_q}.{name}"
        if q in self.funcs:
            return q
        for b in self.classes[cls_q]["resolved"]:
            r = self.find_method(b, name, seen)
            if r:
                return r
        return None

    def walk(self, start, rest):
        cur = start
        for seg in rest:
            if not cur:
                return None
            kind, q = cur
            if kind == "module":
                cur = self.lookup(f"{q}.{seg}")
            elif kind == "class":
                m = self.find_method(q, seg)
                cur = ("func", m) if m else self.lookup(f"{q}.{seg}")
            else:
                return None
        return cur

    def resolve_in(self, fi, dotted, caller=None, depth=0):
        """dotted name as written in file `fi` -> ('func'|'class'|'module', qname) or None."""
        if not dotted or depth > 4:
            return None
        parts = dotted.split(".")
        first = parts[0]
        cq = caller["qname"].rsplit(".", 1)[0] if caller and caller.get("cls") else None
        if first in ("self", "cls") and cq and len(parts) >= 2:
            m = self.find_method(cq, parts[1])
            return ("func", m) if m else None
        if first == "super()" and cq and len(parts) == 2:
            for b in self.classes.get(cq, {}).get("resolved", []):
                m = self.find_method(b, parts[1])
                if m:
                    return ("func", m)
            return None
        if caller and first in caller.get("vartypes", {}) and len(parts) >= 2:
            t = self.type_of(fi, caller["vartypes"][first], depth + 1)
            return self.walk(("class", t), parts[1:]) if t else None
        if first in fi.symbols:
            base, attr = fi.symbols[first]
            start = self.lookup(f"{base}.{attr}" if attr else base)
            if start is None and attr:
                start = self.lookup(base)   # `from pkg import name` where name is an attribute we cannot see
                return None if start is None else self.walk(start, [attr] + parts[1:])
            return self.walk(start, parts[1:])
        return self.walk(self.lookup(f"{fi.module}.{parts[0]}"), parts[1:])

    def type_of(self, fi, expr, depth=0):
        """class qname of a constructor / factory expression, if resolvable."""
        r = self.resolve_in(fi, expr, depth=depth)
        if not r:
            return None
        if r[0] == "class":
            return r[1]
        if r[0] == "func":
            fn = self.funcs[r[1]]
            if fn.get("rettype"):
                f2 = self.file_of.get(r[1])
                rr = self.resolve_in(f2, fn["rettype"], depth=depth + 1) if f2 else None
                return rr[1] if rr and rr[0] == "class" else None
        return None

    # ---- call edges
    def calls(self):
        out = {}
        for fi in self.files.values():
            for caller_q, expr, cls in fi.calls:
                caller = self.funcs.get(caller_q)
                r = self.resolve_in(fi, expr, caller)
                if not r:
                    continue
                kind, q = r
                if kind == "class":                      # constructor call -> __init__
                    init = self.find_method(q, "__init__")
                    if not init:
                        continue
                    q = init
                elif kind != "func":
                    continue
                if q != caller_q:
                    out[(caller_q, q)] = "resolved"
        return out

    # ---- type-flow through class-valued parameters (what a plain call graph cannot see)
    def class_candidates(self, fi, expr, caller=None):
        """Classes a name/expression can denote at a call site: direct class refs, and module-level aliases (one level)."""
        out = set()
        r = self.resolve_in(fi, expr, caller)
        if r and r[0] == "class":
            out.add(r[1])
        first = expr.split(".")[0]
        if "." not in expr and first in fi.aliases:
            for cand in fi.aliases[first]:
                rr = self.resolve_in(fi, cand)
                if rr and rr[0] == "class":
                    out.add(rr[1])
        return out

    def registrations(self):
        """Handlers registered on a class at import time:  Cls.add_constructor(tag, Cls.handler)  ->  Cls -REGISTERS-> handler."""
        reg = {}
        for fi in self.files.values():
            for caller_q, expr, args in fi.callargs:
                if not caller_q.startswith("<module>") or "." not in expr:
                    continue
                rc = self.resolve_in(fi, expr.rsplit(".", 1)[0])
                if not rc or rc[0] != "class":
                    continue
                for _k, aexpr in args:
                    rr = self.resolve_in(fi, aexpr)
                    if rr and rr[0] == "func":
                        reg.setdefault(rc[1], set()).add(rr[1])
        return reg

    def handlers_of(self, cls_q, reg, seen=None):
        seen = seen or set()
        if cls_q in seen or cls_q not in self.classes:
            return set()
        seen.add(cls_q)
        out = set(reg.get(cls_q, ()))
        for b in self.classes[cls_q]["resolved"]:
            out |= self.handlers_of(b, reg, seen)
        return out

    def dispatch_edges(self):
        """Call-site-sensitive type flow. Handles (1) class-valued parameters the callee instantiates, (2) function-valued parameters the
        callee calls, (3) functools.partial bindings, (4) handlers registered on classes. Edges go caller -> target (not callee -> target)
        so one site passing SafeLoader never inherits another site's FullLoader."""
        reg = self.registrations()
        out = {}

        def bind(fi, caller, caller_q, f, args):
            params = f.get("params", [])
            used_cls, called = {}, set()
            for (cq, expr, _cls) in self.files[f["file"]].calls:
                if cq != f["qname"]:
                    continue
                if expr in params:
                    called.add(expr)
                elif "." in expr:
                    var, meth = expr.split(".", 1)
                    t = f.get("vartypes", {}).get(var)
                    if t in params:
                        used_cls.setdefault(t, set()).add(meth.split(".")[0])
            off = 1 if f.get("cls") and params and params[0] in ("self", "cls") else 0
            for key, aexpr in args:
                pname = key if isinstance(key, str) else (params[key + off] if key + off < len(params) else None)
                if pname in used_cls:
                    for c in self.class_candidates(fi, aexpr, caller):
                        tag = f"param-class:{f['name']}({pname}={c.split('.')[-1]})"
                        for m in used_cls[pname] | {"__init__"}:
                            t = self.find_method(c, m)
                            if t and t != caller_q:
                                out[(caller_q, t)] = tag
                        for h in self.handlers_of(c, reg):
                            if h != caller_q:
                                out[(caller_q, h)] = tag + "+registry"
                if pname in called:                                      # function passed in and called by the callee
                    tgt = self.resolve_in(fi, aexpr, caller)
                    if tgt and tgt[0] == "func" and tgt[1] != caller_q:
                        out[(caller_q, tgt[1])] = f"param-func:{f['name']}({pname}={tgt[1].split('.')[-1]})"
                        pq = self.partial_of(fi, aexpr)
                        if pq:                                           # ...and it is a partial with its own class bindings
                            pfi, pfe, pkw = pq
                            pf = self.resolve_in(pfi, pfe)
                            if pf and pf[0] == "func":
                                bind(pfi, caller, caller_q, self.funcs[pf[1]], pkw)

        for fi in self.files.values():
            for caller_q, call_expr, args in fi.callargs:
                if caller_q.startswith("<module>"):
                    continue
                caller = self.funcs.get(caller_q)
                r = self.resolve_in(fi, call_expr, caller)
                if not r or r[0] != "func":
                    continue
                bind(fi, caller, caller_q, self.funcs[r[1]], args)
                pq = self.partial_of(fi, call_expr)                      # direct call of a partial: its bound keywords apply
                if pq:
                    pfi, pfe, pkw = pq
                    pf = self.resolve_in(pfi, pfe)
                    if pf and pf[0] == "func":
                        bind(pfi, caller, caller_q, self.funcs[pf[1]], pkw + args)
        return out

    def partial_of(self, fi, expr):
        """The (file, wrapped function expr, bound kwargs) if `expr` names a functools.partial alias, else None."""
        parts = expr.split(".")
        if parts[0] in fi.symbols and len(parts) == 1:
            base, attr = fi.symbols[parts[0]]
            q = f"{base}.{attr}" if attr else base
        else:
            q = f"{fi.module}.{expr}"
        for _ in range(4):
            if q in self.partials:
                return self.partials[q]
            m, _, n = q.rpartition(".")
            if m in self.modules and n in self.modules[m].symbols:
                b, a = self.modules[m].symbols[n]
                q = f"{b}.{a}" if a else b
            else:
                break
        return None
