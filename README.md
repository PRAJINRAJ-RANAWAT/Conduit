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
| Gateway API | http://localhost:8080 (NGINX -> 2 gateway replicas) |
| Mock LLM A / B | :9000 / :9001 |
| RabbitMQ console | http://localhost:15672 (guest/guest) |

Demo keys: `key-alice` (60k tokens/min), `key-bob` (300 tokens/min), `key-load` (benchmarks).
(Ports 3100/8080 are used because 3000/8000 were taken on the author's machine.)

## Demos, tests, benchmarks
| Command | Shows |
|---|---|
| `./demo_ratelimit.sh` | token bucket: 200s, then 429 + Retry-After |
| `./demo_queue.sh` | jobs, retries, DLQ, idempotency (takes ~50s) |
| `PYTHONPATH=. .venv/bin/python bench/noisy_neighbour.py` | noisy-neighbour experiment, FIFO vs fair (about 8 min) |
| `DISPATCH_MODE=fifo MAX_INFLIGHT=6 docker compose up -d --force-recreate dispatcher` | switch the dispatcher mode (default: fair, 50) |
| `./demo_prompts.sh` | prompt optimiser report |
| `./demo_failover.sh` | provider A fails, B takes over, A recovers |
| `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pytest` | 37 tests on real Redis/RabbitMQ/Postgres (incl. 2 real gateway replicas, real dispatchers) |
| `./bench/run.sh <label> "<note>"` | k6 load test -> `bench/results/<label>/REPORT.md` |
| `PYTHONPATH=. .venv/bin/python bench/accuracy.py` | limiter accuracy across 2 replicas |
| `WORKERS=1 docker compose up -d worker` | change the number of worker replicas (default 3) |
| `./chaos/run_all.sh` | 6 failure scenarios -> `chaos/RESULTS.md` |
| `cd web && npm i && node tests/smoke.mjs` | UI smoke test + screenshots in `docs/screenshots/` |
| `./run_all.sh` | all of the above from a clean start -> `FINAL_RUN.log` |

## Files
| File | What it does |
|---|---|
| `app/main.py` | gateway: the whole request flow in one function, `/stats`, CORS |
| `app/limiter.py` | Redis Lua token bucket + concurrency cap |
| `app/cache.py` | Redis response cache |
| `app/providers.py` | provider fallback + circuit breaker (state in Redis, shared by all replicas) |
| `app/auth.py`, `app/db.py`, `app/schema.sql` | Postgres tenants, hashed keys, usage |
| `app/jobs_api.py` | `POST /jobs` only saves the job (QUEUED) in Postgres |
| `app/dispatcher.py`, `app/drr.py` | dispatcher: fair Deficit Round Robin across tenants, max-in-flight cap, Postgres-advisory-lock leader election, reconciler |
| `app/mq.py`, `app/worker.py` | RabbitMQ topology; worker (fenced claims, lease heartbeat) |
| `app/provider_budget.py` | shared provider budget: interactive traffic first, batch gets the residual |
| `app/optimiser.py`, `app/prompts_api.py`, `app/golden.json` | prompt optimisation |
| `app/mock_provider.py` | fake LLM (can fail on demand; deterministic eval mode) |
| `deploy/nginx/nginx.conf` | load balancer in front of the 2 gateways |
| `web/` | Next.js UI (5 pages) |
| `.github/workflows/ci.yml` | CI: ruff, pytest on real services, gitleaks, Docker build |
| `.github/workflows/release.yml` | multi-arch (amd64+arm64) images to GHCR; deploy to AWS over SSM (off until `DEPLOY_ENABLED=true`) |
| `infra/terraform/` | AWS: EC2 (ARM64) + Elastic IP, 80/443-only security group, SSM secrets, S3 backups, Budgets alarm, GitHub OIDC role |
| `deploy/prod/` | production compose (memory limits, Redis AOF), NGINX + TLS, `deploy.sh` (rolling restart + rollback), backup/restore scripts |
| `docs/DEPLOYMENT.md` | run steps, rollback, backup/restore, secret rotation, cost, memory budget |

Learning notes: `LEARN.md`. Resume bullets: `RESUME.md`.

## Measured results
All numbers live in saved files, none are typed here: `bench/results/<run>/REPORT.md` (k6), `bench/results/STEP2_SUMMARY.md`
(worker scaling, limiter accuracy, revocation, breaker), `bench/results/STEP3_SUMMARY.md` (noisy neighbour, dispatcher failover), `chaos/RESULTS.md`, `FINAL_RUN.log` (full run before step 2).
Headline from step 2 (laptop, mock LLM): backlog drain after load **185 s with 1 worker -> 16 s with 3 workers** (18 s after adding the dispatcher); 50 simultaneous requests
against a 10-request limit across 2 replicas: **exactly 10 pass (3 of 3 runs)**; token over-admission **-0.6%** (never above the limit).
Headline from step 3 (laptop, mock LLM): a tenant flooding 20 jobs/s made a quiet tenant's jobs wait **p99 26 s with plain FIFO dispatch vs 0.4 s with the
fair dispatcher** (max 6 jobs in flight; 4.4 s with 50 in flight); killing the active dispatcher mid-batch of 5,000 jobs: standby leader after **0.31 s**, 0 lost, 0 duplicates.
The optimiser's quality scores come from a deterministic *simulator* and its prices are ASSUMED.

## Deployment (written and rehearsed locally; NOT yet on AWS)
See `docs/DEPLOYMENT.md`. Verified on a laptop with the production compose file: the stack peaks at about **671 MiB** under the k6 load (limits in the file, no OOM kills),
a rolling restart of both gateways under traffic returned **49 of 49** 200s, and a database dump restored with matching row counts. `terraform validate` passes;
`terraform plan/apply`, `deploy.sh` and Let's Encrypt have **not** been run because there is no AWS account access yet. Expected cost: about $17.5/month (ESTIMATE).

## Known limits
- One laptop; k6 shares the CPU with the stack. Not yet measured on separate machines or on AWS.
- Redis down = chat refuses (fail closed), by design.
- While Postgres is down, usage rows are dropped (counted in `/stats` as `usage_rows_dropped`), and a key no gateway has cached cannot be looked up (503).
- Fair scheduling counts every job as cost 1 (a long job and a short job weigh the same). DRR state lives in the active dispatcher's memory, so after a failover it starts a fresh round (still fair, just a restart of the rotation).
- The 0.31 s dispatcher takeover is one run; the standby polls every 1s, so up to ~1 s is the expected range.
- Revoking a key reaches every replica through Redis pub/sub in milliseconds. If a pub/sub message is lost (Redis blip), a 60s cache TTL is the backstop; the subscriber also clears its cache when it reconnects.
- Admin revoke endpoint uses a shared token (`ADMIN_TOKEN`, default is a dev value: change it in any real deployment).
