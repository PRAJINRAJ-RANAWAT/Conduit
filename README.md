# Conduit

A gateway that sits between apps and LLMs. It checks the API key, rate-limits, caches, then calls the model.

## Run it
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d redis
uvicorn app.mock_provider:app --port 9000 &     # fake LLM
uvicorn app.main:app --port 8080                # gateway
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer key-alice" \
  -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"hi"}]}'
pytest
```

## Files
| File | What it does |
|---|---|
| `app/main.py` | The gateway, with the whole request flow in one function |
| `app/limiter.py` | Redis token bucket + concurrency cap (Lua) |
| `app/cache.py` | Redis cache |
| `app/mock_provider.py` | Fake LLM for testing |

## Roadmap (one small step at a time)
1. Gateway + limiter + cache  <- done
2. Postgres for tenants/keys/usage
3. Batch jobs via a queue (RabbitMQ) + workers
4. Provider fallback
5. Load tests with k6, then write up the numbers

## Job queue (step 2)
`POST /jobs` (needs `Idempotency-Key`) saves the job in Postgres and publishes it to RabbitMQ.
A worker (`python -m app.worker`) runs it, saves the result, then acks. Failures retry after
5s / 30s via TTL delay queues; the 3rd failure puts the job in the DLQ. `./demo_queue.sh` shows it.
Ports: gateway 8080, mock LLM 9000 (8000 on this machine was taken by another program).

## Prompt optimisation (step 3)
Prompt versions are immutable (a Postgres trigger refuses edits). `POST /prompts/optimise` scores every
version on a 20-example golden set and picks the fewest-token version within `epsilon` of the baseline.
Quality comes from a deterministic *simulator* in the mock LLM, and prices are ASSUMED, so the
"% saved" shows the pipeline works, not real-model savings. `./demo_prompts.sh` prints the report.

## Postgres + failover (step 4)
Tenants, hashed API keys and usage rows live in Postgres (`app/schema.sql`). The gateway tries
provider A, then B; a circuit breaker (3 failures -> open 10s -> half-open probe) stops hammering a dead
provider. If both are down: fast 503 with `Retry-After`. `./demo_failover.sh` shows it.
Note: breaker state is per gateway process, and a revoked key can take up to 30s to be noticed (auth cache).
