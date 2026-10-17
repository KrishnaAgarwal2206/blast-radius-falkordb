import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
FALKORDB_PASSWORD = os.getenv("FALKORDB_PASSWORD") or None
FALKORDB_USERNAME = os.getenv("FALKORDB_USERNAME") or None
DEFAULT_GRAPH = os.getenv("GRAPH_NAME", "otel")
REPO_PATH = os.getenv("REPO_PATH", str(ROOT / "data" / "repos" / "otel"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-haiku-4-5-20251001")
SPEND_LIMIT_USD = float(os.getenv("SPEND_LIMIT_USD", "15"))
LEDGER_PATH = ROOT / "data" / "spend_ledger.json"
