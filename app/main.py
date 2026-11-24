"""Conduit gateway: every LLM call goes through here.

Flow: API key -> concurrency slot -> token reservation -> cache -> LLM -> settle real usage
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager

import psycopg
import redis.asyncio as redis
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import auth, cache, db, jobs_api, mq, prompts_api, providers, stats
from app.auth import get_tenant
from app.limiter import Limiter

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

@asynccontextmanager
async def lifespan(_):
    db.init()
    auth.seed()
    prompts_api.seed()
    listener = asyncio.create_task(auth.listen_for_revocations(r))   # revoked keys, from all replicas
    yield
    listener.cancel()


app = FastAPI(lifespan=lifespan)
# Lets the web UI (a different origin) call the API from the browser, and read our X-* headers.
app.add_middleware(
    CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3100").split(","),
    allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Conduit-Cache", "X-Conduit-Provider", "X-RateLimit-Remaining-Tokens", "Retry-After"])


@app.exception_handler(redis.RedisError)
async def redis_down(request, exc):
    """Redis holds the limiter and cache. If it is unreachable, fail fast and clearly."""
    return JSONResponse({"detail": "rate limiter unavailable"}, status_code=503,
                        headers={"Retry-After": "5"})




@app.exception_handler(psycopg.Error)
async def db_down(request, exc):
    """Postgres unreachable or its pool exhausted: fail fast and clearly."""
    return JSONResponse({"detail": "database unavailable"}, status_code=503,
                        headers={"Retry-After": "5"})


@app.post("/admin/keys/revoke")
async def revoke_key(body: dict, x_admin_token: str = Header(default="")):
    """Revoke an API key everywhere. Protected by a shared admin token (set ADMIN_TOKEN in prod)."""
    if x_admin_token != os.getenv("ADMIN_TOKEN", "dev-admin-token"):
        raise HTTPException(403, "bad admin token")
    await auth.revoke(r, body["key"])
    return {"revoked": True}


app.include_router(jobs_api.router)
app.include_router(prompts_api.router)
r = redis.from_url(REDIS_URL, decode_responses=True)
limiter = Limiter(r)


def estimate_tokens(body: dict) -> int:
    """Guess the cost BEFORE calling: ~4 characters per input token + the max reply size."""
    chars = sum(len(m["content"]) for m in body["messages"])
    return chars // 4 + 1 + body.get("max_tokens", 50)


def reject(why: str, retry_after: int):
    return HTTPException(429, why, headers={"Retry-After": str(max(retry_after, 1))})


async def record_usage(tenant, provider, in_tokens, out_tokens, latency_ms):
    """Runs AFTER the answer was sent. If Postgres is down we drop the row and count it. We must never
    let an error escape here: an exception after the response started breaks the connection (nginx 502)."""
    try:
        await asyncio.to_thread(
            db.run, "INSERT INTO usage (tenant, provider, input_tokens, output_tokens, latency_ms) "
            "VALUES (%s,%s,%s,%s,%s)", (tenant, provider, in_tokens, out_tokens, latency_ms))
    except Exception:
        await stats.incr(r, "usage_rows_dropped")


@app.post("/v1/chat/completions")
async def chat(body: dict, response: Response, bg: BackgroundTasks,
               tenant: dict = Depends(get_tenant)):
    started = time.time()
    name, tpm = tenant["name"], tenant["tpm"]
    await stats.incr(r, "requests")

    slot = await limiter.acquire_slot(name, tenant["conc"])
    if not slot:
        await stats.incr(r, "rate_limited")
        raise reject("too many concurrent requests", 1)
    try:
        cost = estimate_tokens(body)
        ok, left, retry = await limiter.reserve(name, tpm, cost)
        if not ok:
            await stats.incr(r, "rate_limited")
            raise reject("token limit exceeded", retry)

        key = cache.make_key(name, body)
        result = await cache.get(r, key)
        if result:                                   # cache hit costs nothing: full refund
            left = await limiter.settle(name, tpm, cost, 0)
            await stats.incr(r, "cache_hit")
            response.headers["X-Conduit-Cache"] = "hit"
            provider = "cache"
        else:
            try:
                result, provider = await providers.call(body, r)
            except providers.AllProvidersDown:
                await limiter.settle(name, tpm, cost, 0)       # nothing was used: refund
                raise HTTPException(503, "all providers are down", headers={"Retry-After": "10"})
            used = result["usage"]["prompt_tokens"] + result["usage"]["completion_tokens"]
            left = await limiter.settle(name, tpm, cost, used)  # refund or charge the gap
            await cache.put(r, key, result)
            await stats.incr(r, "cache_miss")
            response.headers["X-Conduit-Cache"] = "miss"
        response.headers["X-RateLimit-Remaining-Tokens"] = str(left)
        response.headers["X-Conduit-Provider"] = provider
        usage = result["usage"]
        bg.add_task(record_usage, name, provider, usage["prompt_tokens"], usage["completion_tokens"],
                    int((time.time() - started) * 1000))
        return result
    finally:
        await limiter.release_slot(name, slot)


@app.get("/stats")
async def get_stats():
    """Real counters for the UI Metrics page (Redis counters + live queue sizes + job counts)."""
    counts = await stats.all_counts(r)
    queue = await asyncio.to_thread(mq.publisher.depth, mq.WORK)   # pika is blocking -> thread
    dlq = await asyncio.to_thread(mq.publisher.depth, mq.DLQ)
    jobs = await asyncio.to_thread(db.run, "SELECT status, count(*) AS n FROM jobs GROUP BY status")
    return {**counts, "queue_depth": queue, "dlq_size": dlq,
            "jobs": {j["status"]: j["n"] for j in jobs},
            "circuits": await providers.states(r)}
