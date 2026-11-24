#!/bin/bash
# Submits 4 jobs: 2 fine, 1 that fails once (retries after 5s), 1 that always fails (-> DLQ after 3 tries).
# Also repeats one Idempotency-Key to show no duplicate. Needs gateway :8080, worker, mock LLM.
G=localhost:8080; A="Authorization: Bearer key-alice"; RUN=$RANDOM
submit() { curl -s -X POST $G/jobs -H "$A" -H "Idempotency-Key: $RUN-$1" -H "Content-Type: application/json" -d "$2"; echo; }
echo "== submit"; submit ok1 '{"prompt":"hello"}'; submit ok2 '{"prompt":"world"}'
submit flaky '{"prompt":"flaky","fail_times":1}'; submit doomed '{"prompt":"doomed","fail_times":99}'
echo "== same Idempotency-Key again (expect same id, HTTP 200)"
curl -s -w " HTTP %{http_code}\n" -X POST $G/jobs -H "$A" -H "Idempotency-Key: $RUN-ok1" -H "Content-Type: application/json" -d '{"prompt":"hello"}'
for t in 1 2 3 4 5 6 7 8; do   # ~45s total: the doomed job needs 5s + 30s of retry delay
  echo "== status after $((t*6))s"; sleep 6
  curl -s "$G/jobs" -H "$A" | python3 -c "import sys,json
for j in json.load(sys.stdin)[:4]: print(' ', j['id'][:8], j['status'].ljust(10), 'attempts=%d' % j['attempts'])"
done
echo "== DLQ (dead jobs)"; curl -s "$G/jobs?status=DEAD" -H "$A"; echo
