"""Conduit gateway: every LLM call goes through here.

Flow: API key -> concurrency slot -> token reservation -> cache -> LLM -> settle real usage
"""
import os
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response

import time
from app import auth, cache, db, jobs_api, prompts_api, providers, stats
from app.auth import get_tenant
from app.limiter import Limiter

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

@asynccontextmanager
async def lifespan(_):
    db.init()
    auth.seed()
    prompts_api.seed()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(redis.RedisError)
async def redis_down(request, exc):
    """Redis holds the limiter and cache. If it is unreachable, fail fast and clearly."""
    return JSONResponse({"detail": "rate limiter unavailable"}, status_code=503,
                        headers={"Retry-After": "5"})


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
                result, provider = await providers.call(body)
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
        bg.add_task(db.run, "INSERT INTO usage (tenant, provider, input_tokens, output_tokens, latency_ms) "
                    "VALUES (%s,%s,%s,%s,%s)", (name, provider, usage["prompt_tokens"],
                    usage["completion_tokens"], int((time.time() - started) * 1000)))
        return result
    finally:
        await limiter.release_slot(name, slot)
