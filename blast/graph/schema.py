"""Graph model: labels, relationship types, indexes, and stats."""
from .client import run

INDEXES = [("Repo", "name"), ("Service", "name"), ("File", "path"), ("Class", "qname"), ("Function", "qname"),
           ("Package", "name"), ("Person", "email"), ("Commit", "sha"), ("Incident", "id")]
KEY = {l: p for l, p in INDEXES}
LABELS = [l for l, _ in INDEXES]
REL_TYPES = ["CONTAINS", "DEFINES", "IMPORTS", "CALLS", "DEPENDS_ON", "OWNS", "AUTHORED", "MODIFIED",
             "AFFECTED", "CAUSED_BY", "RESOLVED_BY", "SIMILAR_TO"]


def create_indexes(graph: str):
    for label, prop in INDEXES:
        try:
            run(graph, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})", readonly=False)
        except Exception as e:  # already exists
            if "already indexed" not in str(e).lower() and "exist" not in str(e).lower():
                raise


def stats(graph: str) -> dict:
    nodes = {l: run(graph, f"MATCH (n:{l}) RETURN count(n)").rows[0][0] for l in LABELS}
    edges = {r: run(graph, f"MATCH ()-[e:{r}]->() RETURN count(e)").rows[0][0] for r in REL_TYPES}
    return {"nodes": nodes, "edges": edges}


def uid(label: str, props: dict) -> str:
    return f"{label}:{props.get(KEY[label])}"
