#!/bin/bash
# Runs the four chaos scenarios against the compose stack and saves each log in chaos/results/.
cd "$(dirname "$0")"
for s in 01_kill_worker 02_stop_redis 03_stop_rabbitmq 04_provider_down 05_stop_postgres; do
  echo "=== $s"; PYTHONPATH=.. ../.venv/bin/python $s.py 2>&1 | tee results/$s.log
done
