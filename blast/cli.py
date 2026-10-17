"""`python -m blast.cli investigate "<trace | service | file>" [--llm] [--graph otel] [--json]`"""
import argparse
import json
import sys

from . import config
from .agent.loop import investigate


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["investigate"])
    ap.add_argument("text", help="stack trace, service, file or function (use - for stdin)")
    ap.add_argument("--graph", default=config.DEFAULT_GRAPH)
    ap.add_argument("--llm", action="store_true", help="use the Anthropic agent (costs money) instead of the deterministic pipeline")
    ap.add_argument("--no-remember", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = sys.stdin.read() if a.text == "-" else a.text

    def emit(e):
        t = e["type"]
        if a.json:
            print(json.dumps(e, default=str))
        elif t == "tool_call":
            print(f"\n▶ {e['tool']}({json.dumps(e['args'], default=str)[:100]})")
        elif t == "graph_query":
            print(f"   cypher [{e['ms']}ms, {e['rows']} rows] {e['cypher'][:110]}")
        elif t == "tool_result":
            print(f"   ✓ {e['summary']}")
        elif t == "thinking":
            print(e["text"], end="", flush=True)
        elif t == "error":
            print(f"   ! {e['message']}")

    ans = investigate(a.graph, text, emit, use_llm=a.llm, remember=not a.no_remember)
    if ans and not a.json:
        print("\n=== ANSWER ===")
        print(ans["summary"], "| confidence", ans["confidence"])
        for c in ans["claims"]:
            print(f"- [{c['kind']}] {c['text']}  (paths: {', '.join(c['path_ids'])})")
        for p in ans["evidence_paths"][:6]:
            print(f"    {p['path_id']}: {p['sentence']}")
        if ans["dropped_unverified_claims"]:
            print("dropped unverified claims:", ans["dropped_unverified_claims"])


if __name__ == "__main__":
    main()
