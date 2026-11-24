#!/bin/bash
# The full check from a clean start: wipe everything, start the stack, run tests, demos, load test,
# chaos tests and UI smoke test. Output goes to FINAL_RUN.log. Takes about 12 minutes.
cd "$(dirname "$0")"
step() { echo; echo "################ $*"; }
step "clean start"; docker compose down -v 2>&1 | tail -1; docker compose up -d --build 2>&1 | tail -2
until [ "$(curl -s -o /dev/null -w %{http_code} localhost:8080/stats)" = "200" ]; do sleep 2; done
until curl -s -o /dev/null localhost:3100; do sleep 2; done
step "pytest";                 .venv/bin/pytest -q 2>&1 | tail -4
step "demo_ratelimit.sh";      ./demo_ratelimit.sh
step "demo_prompts.sh";        ./demo_prompts.sh
step "demo_failover.sh";       ./demo_failover.sh
step "demo_queue.sh";          ./demo_queue.sh
step "bench/run.sh (k6)";      ./bench/run.sh 2>&1 | sed -n '/# Load test results/,$p'
step "chaos/run_all.sh";       ./chaos/run_all.sh
step "UI smoke test";          (cd web && node tests/smoke.mjs)
step "UI landing after benchmark"; (cd web && node tests/smoke.mjs 2>&1 | grep "landing stats")
