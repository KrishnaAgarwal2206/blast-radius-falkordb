FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY blast ./blast
COPY web ./web
COPY data/replays ./data/replays
ENV PYTHONUNBUFFERED=1 FALKORDB_HOST=falkordb
EXPOSE 8000
CMD ["uvicorn", "blast.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
