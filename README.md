# Conduit

A gateway between your apps and LLMs. It checks the API key, rate-limits by tokens, caches, calls a healthy
provider, and runs bulk work through a queue. Everything runs locally against a mock LLM (no money spent).

## Run everything (one command)
```
docker compose up -d --build
```
| What | Where |
|---|---|
| UI | http://localhost:3100 |
| Gateway API | http://localhost:8080 |
| Mock LLM A / B | :9000 / :9001 |
| RabbitMQ console | http://localhost:15672 (guest/guest) |

Demo keys: `key-alice` (60k tokens/min), `key-bob` (300 tokens/min), `key-load` (benchmarks).
(Ports 3100/8080 are used because 3000/8000 were taken on the author's machine.)

## Demos, tests, benchmarks
| Command | Shows |
|---|---|
| `./demo_ratelimit.sh` | token bucket: 200s, then 429 + Retry-After |
| `./demo_queue.sh` | jobs, retries, DLQ, idempotency (takes ~50s) |
| `./demo_prompts.sh` | prompt optimiser report |
| `./demo_failover.sh` | provider A fails, B takes over, A recovers |
| `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pytest` | 25 tests on real Redis/RabbitMQ/Postgres |
| `./bench/run.sh` | k6 load test -> `bench/results/REPORT.md` |
| `./chaos/run_all.sh` | 4 failure scenarios -> `chaos/RESULTS.md` |
| `cd web && npm i && node tests/smoke.mjs` | UI smoke test + screenshots in `docs/screenshots/` |
| `./run_all.sh` | all of the above from a clean start -> `FINAL_RUN.log` |

## Files
| File | What it does |
|---|---|
| `app/main.py` | gateway: the whole request flow in one function, `/stats`, CORS |
| `app/limiter.py` | Redis Lua token bucket + concurrency cap |
| `app/cache.py` | Redis response cache |
| `app/providers.py` | provider fallback + circuit breaker |
| `app/auth.py`, `app/db.py`, `app/schema.sql` | Postgres tenants, hashed keys, usage |
| `app/jobs_api.py`, `app/mq.py`, `app/worker.py` | job queue |
| `app/optimiser.py`, `app/prompts_api.py`, `app/golden.json` | prompt optimisation |
| `app/mock_provider.py` | fake LLM (can fail on demand; deterministic eval mode) |
| `web/` | Next.js UI (5 pages) |

Learning notes: `LEARN.md`. Resume bullets: `RESUME.md`.

## Measured results
All numbers live in saved files, none are typed here: `bench/results/REPORT.md` (k6), `chaos/RESULTS.md`,
`FINAL_RUN.log` (last full run). Quality scores in the optimiser come from a deterministic *simulator* and its
prices are ASSUMED.

## Known limits
- One laptop; k6 shares the CPU with the stack. One gateway process, one worker.
- Under the k6 load, one worker took ~3 minutes after the load ended to finish 1,101 jobs (it is slower than the submit rate). Add workers to go faster.
- Circuit-breaker state is per gateway process; a revoked key can be accepted for up to 30s (auth cache).
- Redis down = chat refuses (fail closed), by design. Postgres-down was not tested.
- Not pushed to GitHub; the UI "GitHub" button points to `#` until `NEXT_PUBLIC_GITHUB_URL` is set.
