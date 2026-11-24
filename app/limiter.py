"""Rate limiter: max N requests per minute per tenant, shared by all gateway copies via Redis.

Redis runs INCR atomically, so two gateways can never both slip past the limit.
"""
import time
import redis.asyncio as redis


async def allow(r: redis.Redis, tenant: str, limit_per_minute: int) -> bool:
    minute = int(time.time() // 60)
    key = f"rl:{tenant}:{minute}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 120)  # old windows clean themselves up
    return count <= limit_per_minute
