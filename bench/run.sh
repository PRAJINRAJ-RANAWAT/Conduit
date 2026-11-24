#!/bin/bash
# Runs the k6 load test (in Docker) against the gateway on :8080, then writes bench/results/REPORT.md.
# Start the stack first (see README). Everything runs on ONE laptop, so k6 shares CPU with the system under test.
cd "$(dirname "$0")/.."
mkdir -p bench/results
{ echo "date: $(date -u +%FT%TZ)"; echo "cpu: $(sysctl -n machdep.cpu.brand_string) ($(sysctl -n hw.ncpu) cores)";
  echo "ram: $(( $(sysctl -n hw.memsize) / 1073741824 )) GB"; echo "docker VM memory: $(docker info --format '{{.MemTotal}}')";
  echo "gateway: 1 uvicorn process, 1 worker process, mock LLM A/B (0.2s sleep), Redis/RabbitMQ/Postgres in Docker";
} > bench/results/hardware.txt
docker compose exec -T redis redis-cli flushall > /dev/null
.venv/bin/python -c "from app import db; db.init(); db.run('TRUNCATE jobs, usage')"
docker run --rm -i -e RUN=$RANDOM -v "$PWD/bench:/bench" grafana/k6 run \
  --out json=/bench/results/raw.json /bench/k6/load.js
gzip -f bench/results/raw.json
PYTHONPATH=. .venv/bin/python bench/report.py
