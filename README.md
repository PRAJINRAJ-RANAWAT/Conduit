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
