"""Cache: same question from the same tenant -> reuse the answer, skip the LLM."""
import hashlib
import json

import redis.asyncio as redis


def make_key(tenant: str, body: dict) -> str:
    raw = json.dumps(body, sort_keys=True)
    return f"cache:{tenant}:{hashlib.sha256(raw.encode()).hexdigest()}"


async def get(r: redis.Redis, key: str):
    value = await r.get(key)
    return json.loads(value) if value else None


async def put(r: redis.Redis, key: str, response: dict, ttl: int = 300):
    await r.set(key, json.dumps(response), ex=ttl)
