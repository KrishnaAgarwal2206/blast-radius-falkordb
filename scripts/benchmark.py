"""Print the scanner-vs-graph comparison table from the recorded snapshots (data/supply/*.json). Everything shown is a real query result."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ["httpie", "cookiecutter", "precommit", "yamlfull"]

rows = []
for a in APPS:
    p = ROOT / "data" / "supply" / f"{a}.json"
    if not p.exists():
        continue
    s = json.loads(p.read_text())
    c, hc = s["counts"], s["scanner"]["high_or_critical"]
    reach_hc = sum(1 for f in s["findings"] if f["verdict"] == "reachable" and f["severity"] in ("HIGH", "CRITICAL"))
    plan = [x for x in s["plan"] if x.get("to_version")]
    ok = [x for x in plan if s["checks"].get(x["package"], {}).get("checks") and all(c2["ok"] for c2 in s["checks"][x["package"]]["checks"])]
    cleared = sum(len(x["cleared_in_scope"]) for x in ok)
    poss = sum(1 for f in s["findings"] if f.get("reason") == "possible_via_dynamic_dispatch")
    tbl = sum(1 for f in s["findings"] if f["verdict"] == "reachable" and "registry-dict" in (f.get("via") or []))
    rows.append((s["title"], s["scanner"]["total"], hc, f"{c['reachable']} ({tbl} via handler table)", c["no_path_found"], f"{c['unknown']} ({poss} possible path)", reach_hc, len(plan), len(ok), cleared))

print("| App (pinned lock) | Scanner alerts | of which high/critical | Reachable | No path found | Unknown | Upgrades planned | Pass smoke checks | Reachable alerts cleared by passing upgrades |")
print("|---|---|---|---|---|---|---|---|---|")
for t, tot, hc, r, n, u, rhc, np_, nok, cl in rows:
    print(f"| {t} | {tot} | {hc} | {r} | {n} | {u} | {np_} | {nok} | {cl} |")
tt = sum(r[1] for r in rows)
rr = sum(int(str(r[3]).split()[0]) for r in rows)
print(f"\nTotal: {tt} alerts, {rr} reachable ({100 * rr / max(tt, 1):.0f}%).")
