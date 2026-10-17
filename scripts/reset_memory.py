"""Delete live (recorded) incidents so the demo starts with a clean memory. Usage: python scripts/reset_memory.py [graph]"""
import sys

from blast.graph.client import run

g = sys.argv[1] if len(sys.argv) > 1 else "otel"
n = run(g, "MATCH (i:Incident {source:'live'}) DETACH DELETE i RETURN count(i)", readonly=False).rows
print("deleted live incidents:", n)
