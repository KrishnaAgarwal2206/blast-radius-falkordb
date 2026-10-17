# Deploying a live demo (FalkorDB Cloud + Render)

The free FalkorDB Cloud tier has **no persistence and stops after idle**, so the graphs must be re-seedable with one command. Seeding is deterministic and offline-friendly: advisory records, fix diffs and PyPI metadata used for the demo apps are committed in `data/cache/`, and the smoke-check results are committed in `data/supply/*.json` (the throw-away-venv checks need a Python 3.11 runner and are not re-run on the server).

1. Create a free FalkorDB Cloud instance (app.falkordb.cloud). Note host, port, password.
2. Seed it from your machine (a few minutes; the first run downloads the pinned wheels from PyPI):
   ```bash
   export FALKORDB_HOST=<host> FALKORDB_PORT=<port> FALKORDB_PASSWORD=<pw>
   for a in yamlfull precommit cookiecutter httpie; do python -m blast.supply.pipeline $a --no-checks; done
   ```
   (`--no-checks` keeps the recorded smoke-check results.) Optional v1 incident mode: `python -m blast.ingest.cli https://github.com/open-telemetry/opentelemetry-python --graph otel --ref 2fa016b27d9b817aee88ea58be1bd0bc10fd2a40`.
3. Deploy the web service: Render -> New -> Blueprint -> this repo (uses `render.yaml`); set the env vars. `ANTHROPIC_API_KEY` is optional; deterministic mode needs none. Keep `SPEND_LIMIT_USD` low on a public URL.
4. Open `https://<service>.onrender.com`. If the database is cold or empty the UI falls back to recorded replays (`/?replay=supply-httpie`, `/?replay=supply-yaml-0`), which need neither FalkorDB nor an LLM.
5. Before judging, hit `/api/health` to wake both services, and re-run step 2 if the free instance was reset.
