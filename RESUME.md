# Resume material (only numbers measured in this repo; limits stated in each bullet)

**Conduit: multi-tenant LLM traffic gateway** | Python, FastAPI, Redis (Lua, pub/sub), RabbitMQ, PostgreSQL, NGINX, Docker, k6, GitHub Actions, Next.js

- Built an LLM gateway (2 replicas behind NGINX) with a Redis Lua token-bucket limiter, response cache and provider failover; a k6 test with 50 concurrent users measured **p99 295 ms at 259 req/s with 0% unexpected errors** on one laptop with a mock LLM that sleeps 0.2s ([result](bench/results/original-1gw-1worker/REPORT.md); latest run on 2 gateways + 3 workers: p99 309 ms, 271 req/s, [result](bench/results/2gw-3workers/REPORT.md)).
- Verified rate-limit accuracy across replicas: **50 simultaneous requests against a 10-request budget admitted exactly 10 in 3 of 3 runs**, and under 100 concurrent clients the token limiter's over-admission was **-0.6%** (never above the limit) ([result](bench/results/STEP2_SUMMARY.md)). One laptop, mock LLM.
- Scaled the RabbitMQ job workers from 1 to 3 replicas: the backlog after a 1,101-job load test drained in **16 s instead of 181-185 s**, with **0 jobs lost** in every run ([result](bench/results/STEP2_SUMMARY.md)). Same laptop; k6 shares its CPU.
- Made state shared across gateway replicas: Redis pub/sub revocation (a revoked key was rejected on both replicas, **0.03 s** in the one run observed; the test allows 5 s) and a Redis-backed circuit breaker (replica 2 saw provider A "open" after only replica 1 had seen it fail) ([tests](tests/test_replicas.py)).
- Wrote five scripted chaos tests (worker kill, Redis, RabbitMQ, Postgres, provider outage); the first runs **found three real bugs** (worker never reconnected to RabbitMQ; raw HTTP 500 when Redis was down; HTTP 502 when Postgres was down because a background task failed after the response started), all fixed and re-verified; **29 automated tests** run against real Redis, RabbitMQ and Postgres, and CI runs them on every PR ([chaos results](chaos/RESULTS.md)).

Optional line, with its caveat: a prompt optimiser picked a version scoring 0.95 vs the 1.00 baseline at **46.5% lower token cost**. This uses a *simulated* quality model and *assumed* prices, so say "on a simulated eval" if you quote it.

ATS keywords actually exercised by the code: Redis, Lua, pub/sub, RabbitMQ, PostgreSQL, FastAPI, NGINX, load balancing, Docker Compose, GitHub Actions, rate limiting, idempotency, circuit breaker, dead-letter queue, k6, load testing, chaos testing, Next.js, Playwright.
