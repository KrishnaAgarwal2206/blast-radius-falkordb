"""Record real runs as replay files (demo insurance). Usage: python scripts/record_replays.py [--llm]
Each file is the genuine SSE event stream of a run against the live graph, not synthesized."""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "replays"
SCEN = {
    "scenario3": (ROOT / "data" / "scenario3_trace.txt").read_text(encoding="utf-8").strip(),
    "scenario1": "opentelemetry-exporter-otlp-proto-grpc",
    "scenario2": "opentelemetry-sdk/src/opentelemetry/sdk/metrics/_internal/view.py",
}


def record(name, text, llm=False, remember=False):
    r = httpx.post(f"{BASE}/api/investigate", json={"input": text, "llm": llm, "remember": remember}, timeout=30).json()
    rid = r["run_id"]
    events = []
    with httpx.stream("GET", f"{BASE}/api/runs/{rid}/events", timeout=180) as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(events))
    fin = events[-1]
    print(name, len(events), "events", fin.get("ms"), "ms", "cost", fin.get("cost_usd"))


if __name__ == "__main__":
    for n, t in SCEN.items():
        record(n, t)
    if "--llm" in sys.argv:
        record("scenario3-llm", "Metrics stopped exporting in production. Here is the trace:\n" + SCEN["scenario3"], llm=True)
