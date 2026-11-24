#!/bin/bash
# Usage: ./bench/run.sh <label> "<topology note>"      e.g. ./bench/run.sh 3-workers "2 gateways + nginx, 3 workers"
# Runs the k6 load test (in Docker) against http://localhost:8080 and writes bench/results/<label>/REPORT.md.
# Everything runs on ONE laptop, so k6 shares CPU with the system under test.
cd "$(dirname "$0")/.."
LABEL=${1:?give a label}; TOPOLOGY=${2:-unspecified}
OUT=bench/results/$LABEL; mkdir -p $OUT
{ echo "date: $(date -u +%FT%TZ)"; echo "cpu: $(sysctl -n machdep.cpu.brand_string) ($(sysctl -n hw.ncpu) cores)";
  echo "ram: $(( $(sysctl -n hw.memsize) / 1073741824 )) GB"; echo "docker VM memory: $(docker info --format '{{.MemTotal}}')";
  echo "topology: $TOPOLOGY"; echo "worker containers running: $(docker compose ps --format '{{.Service}}' | grep -c '^worker')";
  echo "gateway containers running: $(docker compose ps --format '{{.Service}}' | grep -c '^gateway')";
  echo "mock LLM A/B: 0.2s sleep; Redis/RabbitMQ/Postgres in Docker";
} > $OUT/hardware.txt
docker compose exec -T redis redis-cli flushall > /dev/null
.venv/bin/python -c "from app import db; db.init(); db.run('TRUNCATE jobs, usage')"
docker run --rm -i -e RUN=$RANDOM -e LABEL=$LABEL -v "$PWD/bench:/bench" grafana/k6 run \
  --out json=/bench/results/$LABEL/raw.json /bench/k6/load.js
gzip -f $OUT/raw.json
PYTHONPATH=. .venv/bin/python bench/report.py $LABEL
