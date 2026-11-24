# Resume material (only numbers measured in this repo)

**Conduit: multi-tenant LLM traffic gateway** | Python, FastAPI, Redis (Lua), RabbitMQ, PostgreSQL, Docker, k6, Next.js

- Built an LLM gateway with a Redis Lua token-bucket rate limiter, response cache, and provider failover with a circuit breaker; a k6 load test (50 concurrent users, one laptop, mock LLM with a 0.2s delay) measured **p99 295 ms at 259 req/s with 0% unexpected errors** (`bench/results/REPORT.md`).
- Verified rate-limit accuracy under concurrency: **50 simultaneous requests against a 10-request budget admitted exactly 10** (pytest, real Redis); under load the small-quota tenant received 429 on **99.9%** of requests while the large-quota tenant received 0%.
- Built an at-least-once job queue (RabbitMQ publisher confirms, ack-after-save, idempotent worker, delay-queue retries, DLQ): **0 of 1,101 jobs lost** under load, and a scripted `kill -9` of the worker mid-job still finished **5 of 5 jobs** (`chaos/RESULTS.md`).
- Wrote four scripted chaos tests (worker kill, Redis down, RabbitMQ down, provider down); the first run **found two real bugs** (worker never reconnected to RabbitMQ; raw HTTP 500 when Redis was down), both fixed and re-verified; **25 automated tests** run against real Redis, RabbitMQ and Postgres.

Optional line, with its caveat: a prompt optimiser picked a version scoring 0.95 vs the 1.00 baseline at **46.5% lower token cost**. This uses a *simulated* quality model and *assumed* prices, so say "on a simulated eval" if you quote it.

ATS keywords actually exercised by the code: Redis, Lua, RabbitMQ, PostgreSQL, FastAPI, Docker Compose, rate limiting, idempotency, circuit breaker, dead-letter queue, k6, load testing, chaos testing, Next.js, Playwright.
