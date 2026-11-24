"""Tiny counters kept in Redis (shown by GET /stats and the UI Metrics page)."""
import redis.asyncio as redis


async def incr(r: redis.Redis, name: str):
    await r.hincrby("stats", name, 1)


async def all_counts(r: redis.Redis) -> dict:
    return {k: int(v) for k, v in (await r.hgetall("stats")).items()}
