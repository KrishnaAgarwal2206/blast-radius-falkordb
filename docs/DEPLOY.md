# Deploying a live demo (FalkorDB Cloud + Render)

The free FalkorDB Cloud tier has **no persistence and stops after idle**, so the graph must be re-seedable in one command.

1. Create a free FalkorDB Cloud instance (app.falkordb.cloud). Note host, port, password.
2. Seed it from your machine (≈1 min, clones OpenTelemetry-Python at the pinned SHA):
   ```bash
   FALKORDB_HOST=<host> FALKORDB_PORT=<port> FALKORDB_PASSWORD=<pw> \
   python -m blast.ingest.cli https://github.com/open-telemetry/opentelemetry-python --graph otel --ref 2fa016b27d9b817aee88ea58be1bd0bc10fd2a40
   ```
3. Deploy the web service: Render → New → Blueprint → this repo (uses `render.yaml`); set the env vars above. `ANTHROPIC_API_KEY` is optional; the deterministic mode needs none. Keep `SPEND_LIMIT_USD` low on a public URL.
4. Open `https://<service>.onrender.com`. If the database is cold/empty, the UI falls back to the recorded replays (`/?replay=scenario3`), which need neither FalkorDB nor an LLM.
5. Before judging, hit `/api/health` to wake both services.
