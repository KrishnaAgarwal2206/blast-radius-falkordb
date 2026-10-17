"""python scripts/sc_build.py <app> : build graph + advisories + print reachability verdicts"""
import sys
from pathlib import Path
from blast.supply import advisories, dists
from blast.supply.apps import APPS
from blast.supply.build import build, graph_name
from blast.supply.analysis import verdicts

app = sys.argv[1]
build(app)
pins = dists.parse_pins(Path(APPS[app]["pins"]).read_text())
advisories.ingest_advisories(graph_name(app), pins)
r = verdicts(graph_name(app))
print(r.data["counts"], "of", r.data["total"], f"{r.ms:.0f} ms")
for f in r.data["findings"]:
    print(f"{f['verdict']:14} {str(f['cvss']):>4} {f['severity']:8} {f['package']:12} {f['id']:16} map={f['mapping']:9} fixed={','.join(f['fixed'][:2])}  {(f.get('target') or '')[-50:]}")
