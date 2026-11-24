"""Conduit gateway: every LLM call goes through here.

Flow: API key -> concurrency slot -> token reservation -> cache -> LLM -> settle real usage
"""
import os
import httpx
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Response

from app import cache, db, jobs_api, stats
from app.auth import get_tenant
from app.limiter import Limiter

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PROVIDER_URL = os.getenv("PROVIDER_URL", "http://localhost:9000")

@asynccontextmanager
async def lifespan(_):
    db.init()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(jobs_api.router)
r = redis.from_url(REDIS_URL, decode_responses=True)
limiter = Limiter(r)


def estimate_tokens(body: dict) -> int:
    """Guess the cost BEFORE calling: ~4 characters per input token + the max reply size."""
    chars = sum(len(m["content"]) for m in body["messages"])
    return chars // 4 + 1 + body.get("max_tokens", 50)


def reject(why: str, retry_after: int):
    return HTTPException(429, why, headers={"Retry-After": str(max(retry_after, 1))})


@app.post("/v1/chat/completions")
async def chat(body: dict, response: Response, tenant: dict = Depends(get_tenant)):
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
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                up = await client.post(f"{PROVIDER_URL}/v1/chat/completions", json=body)
            up.raise_for_status()
            result = up.json()
            used = result["usage"]["prompt_tokens"] + result["usage"]["completion_tokens"]
            left = await limiter.settle(name, tpm, cost, used)  # refund or charge the gap
            await cache.put(r, key, result)
            await stats.incr(r, "cache_miss")
            response.headers["X-Conduit-Cache"] = "miss"
        response.headers["X-RateLimit-Remaining-Tokens"] = str(left)
        return result
    finally:
        await limiter.release_slot(name, slot)
