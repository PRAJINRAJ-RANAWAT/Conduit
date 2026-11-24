# Chaos results

Run with `./chaos/run_all.sh` against the docker compose stack (2 gateways behind NGINX, 3 workers as of step 2). Logs: `chaos/results/*.log` (final run) and
`chaos/results/first_run/*.log` (first run, before two fixes). The expectations were written in each script
*before* it was first run.

| # | Fault | Expected | Actual, first run | Fix | Actual, after fix |
|---|---|---|---|---|---|
| 1 | `kill -9` the worker during jobs | Message returns to the queue, new worker retakes it, 0 jobs lost, killed job has attempts >= 2 | PASS: 5/5 SUCCEEDED, 1 job retaken (attempts=2) | none needed | same |
| 2 | Stop Redis | Chat fails fast with a clean 503; jobs still work; chat recovers when Redis returns | **Chat returned a raw HTTP 500** (unhandled exception). Jobs OK, recovered OK. (My first check accepted 500, so it "passed"; the clean-503 expectation was not met.) | gateway now catches Redis errors -> 503 + `Retry-After` | 503 in 0.04s, jobs 202, chat recovered |
| 3 | Stop RabbitMQ | `POST /jobs` -> 503, retry with same key queues it without a duplicate, chat unaffected, worker reconnects, 0 lost | **FAIL: the worker process crashed** (`StreamLostError`) and never came back; the retried job stayed QUEUED forever | worker loops: on any connection error wait 3s and reconnect | 503 while down, same-key retry accepted (HTTP 200), job SUCCEEDED, chat HTTP 200 throughout |
| 4 | Provider A returns 500s | Chat served from B, A's breaker opens, fast 503 when both are down, A restored after cooldown | PASS: all 200 from B; both down -> 503 + Retry-After 10 in 0.02s; after 11s A serves again | none needed | same |
| 5 | Stop Postgres | Cached keys still answered (200); uncached key and `POST /jobs` fail fast with 503; everything recovers with no restart | **Cached chat OK, but uncached chat and `POST /jobs` returned HTTP 502 from NGINX.** Cause: the usage-row insert runs after the response was sent; when Postgres was down it raised after the response had started, which broke the kept-alive connection NGINX reuses, so the *next* request got a 502. (Log: `chaos/results/first_run/05_stop_postgres.log`; gateway log said `Caught handled exception, but response already started`.) Recovery was fine. | usage insert now catches its own errors and counts `usage_rows_dropped` in `/stats`; DB pool gives up after 2s -> clean 503 | cached chat 200 x6 (both replicas), uncached chat 503 in 2.0s, `POST /jobs` 503 in 2.0s, recovered with no restart, a job finished |

Scenario 5 first-run note: the DB pool timeout (2s) and the psycopg->503 handler were added *before* that first run, so the 502 was the part
I did not predict. Scenarios 1-4 were re-run unchanged on the new topology (3 workers: the `kill -9` retook 3 jobs this time) and still pass.

## What these runs do not prove
- One short run per scenario on one laptop, not a randomized 30-minute soak.
- Redis down also disables the limiter and cache completely (the gateway rejects chat instead of serving unprotected). That is a deliberate fail-closed choice, not graceful degradation.
- While Postgres is down, usage rows are dropped (counted, not queued): usage numbers are an undercount for that window.
- A key that is not in a gateway's cache cannot be looked up while Postgres is down (503), even if it is valid.
