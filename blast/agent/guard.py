"""Guard for agent-authored Cypher: read-only, single statement, bounded."""
import re

ALLOWED_PROCS = re.compile(r"CALL\s+algo\.(pageRank|betweenness|WCC|labelPropagation|BFS|SPpaths)\b", re.I)
FORBIDDEN = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH|CALL|DBMS|APOC)\b", re.I)
START = re.compile(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN|CALL\s+algo\.)", re.I)
STRINGS = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
MAX_LIMIT = 200

SCHEMA_HINT = ("Labels/keys: Service(name,dir) File(path,service,loc) Class(qname) Function(qname,name,file,start,end) "
               "Package(name) Person(email,name,bot) Commit(sha,ts,msg,pr) Incident(id,title,ts,source). "
               "Rels: CONTAINS, DEFINES, IMPORTS(File→File), CALLS(Function→Function), DEPENDS_ON(Service→Service|Package), "
               "OWNS{score}, AUTHORED, MODIFIED(Commit→File|Function), AFFECTED(Incident→File|Service), CAUSED_BY, RESOLVED_BY, SIMILAR_TO.")


class GuardError(ValueError):
    pass


def check(query: str) -> str:
    """Return a safe, bounded query or raise GuardError."""
    q = (query or "").strip().rstrip(";").strip()
    if not q:
        raise GuardError("empty query")
    if ";" in STRINGS.sub("''", q):
        raise GuardError("multiple statements are not allowed")
    bare = STRINGS.sub("''", q)
    if not START.match(bare):
        raise GuardError("query must start with MATCH/OPTIONAL MATCH/WITH/UNWIND/RETURN or CALL algo.*")
    stripped = ALLOWED_PROCS.sub("", bare)
    m = FORBIDDEN.search(stripped)
    if m:
        raise GuardError(f"forbidden keyword: {m.group(0).upper()} (read-only graph access)")
    lim = re.search(r"\bLIMIT\s+(\d+)", q, re.I)
    if lim:
        if int(lim.group(1)) > MAX_LIMIT:
            q = re.sub(r"\bLIMIT\s+\d+", f"LIMIT {MAX_LIMIT}", q, flags=re.I)
    else:
        q += f" LIMIT {MAX_LIMIT // 2}"
    return q
