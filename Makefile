PY=.venv/Scripts/python
.PHONY: up ingest test demo
up:
	docker compose up --build -d
ingest:
	docker compose run --rm ingest
test:
	$(PY) -m pytest -q
