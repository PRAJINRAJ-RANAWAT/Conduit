"""Conduit gateway: every LLM call goes through here.

Request flow:  API key -> rate limit -> cache -> LLM provider -> save to cache
"""
import os
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Response

from app import cache, limiter

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PROVIDER_URL = os.getenv("PROVIDER_URL", "http://localhost:9000")

# Phase 1 keeps tenants in a dict. A Postgres table replaces this later.
TENANTS = {
    "key-alice": {"name": "alice", "rpm": 60},
    "key-bob": {"name": "bob", "rpm": 5},
}

app = FastAPI()
r = redis.from_url(REDIS_URL, decode_responses=True)


@app.post("/v1/chat/completions")
async def chat(body: dict, response: Response, authorization: str = Header(default="")):
    # 1. Who are you?
    tenant = TENANTS.get(authorization.removeprefix("Bearer "))
    if not tenant:
        raise HTTPException(401, "bad api key")

    # 2. Are you allowed to call right now?
    if not await limiter.allow(r, tenant["name"], tenant["rpm"]):
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"})

    # 3. Have we answered this before?
    key = cache.make_key(tenant["name"], body)
    cached = await cache.get(r, key)
    if cached:
        response.headers["X-Conduit-Cache"] = "hit"
        return cached

    # 4. Ask the LLM
    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.post(f"{PROVIDER_URL}/v1/chat/completions", json=body)
    upstream.raise_for_status()
    result = upstream.json()

    # 5. Remember it
    await cache.put(r, key, result)
    response.headers["X-Conduit-Cache"] = "miss"
    return result
