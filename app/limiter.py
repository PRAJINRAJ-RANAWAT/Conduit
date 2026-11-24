"""Rate limiting, all done inside Redis so every gateway copy shares the same numbers.

Two protections per tenant:
  1. TOKEN BUCKET  - a bucket of LLM tokens that refills over time.
       reserve(estimate) before the call, then settle() with the real usage afterwards
       (refund if we guessed too high, charge if too low).
  3. CONCURRENCY CAP - at most N calls in flight. Each slot expires on its own, so a
       crashed request can never leak a slot forever.

Lua scripts run atomically in Redis (nothing else runs in the middle), and they read the
clock from Redis (redis.call('TIME')) so gateway machines with different clocks agree.
"""
import uuid
import redis.asyncio as redis

# KEYS[1]=bucket  ARGV: capacity, refill_per_sec, cost   -> {allowed, tokens_left, retry_after_ms}
RESERVE = """
local t = redis.call('TIME'); local now = t[1] * 1000 + math.floor(t[2] / 1000)
local b = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local cap, rate, cost = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local tokens = tonumber(b[1]) or cap
local ts = tonumber(b[2]) or now
tokens = math.min(cap, tokens + (now - ts) * rate / 1000)      -- refill
local ok, retry = 0, 0
if tokens >= cost then tokens = tokens - cost; ok = 1
else retry = math.ceil((cost - tokens) * 1000 / rate) end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', KEYS[1], 3600000)
return {ok, math.floor(tokens), retry}
"""

# KEYS[1]=bucket  ARGV: capacity, delta  (delta>0 refund, delta<0 charge extra) -> tokens_left
# Charging can push the bucket below zero ("debt"): the tenant must wait before the next call.
SETTLE = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens')) or tonumber(ARGV[1])
tokens = math.min(tonumber(ARGV[1]), tokens + tonumber(ARGV[2]))
redis.call('HSET', KEYS[1], 'tokens', tokens)
return math.floor(tokens)
"""

# KEYS[1]=zset of slot_id -> expiry_ms   ARGV: max_concurrency, slot_id, ttl_ms -> 1/0
ACQUIRE = """
local t = redis.call('TIME'); local now = t[1] * 1000 + math.floor(t[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)             -- drop expired slots
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[2])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


class Limiter:
    def __init__(self, r: redis.Redis):
        self.reserve_lua = r.register_script(RESERVE)
        self.settle_lua = r.register_script(SETTLE)
        self.acquire_lua = r.register_script(ACQUIRE)
        self.r = r

    async def reserve(self, tenant: str, tpm: int, cost: int):
        """Returns (allowed, tokens_left, retry_after_seconds)."""
        ok, left, retry_ms = await self.reserve_lua(
            keys=[f"rl:tok:{tenant}"], args=[tpm, tpm / 60, cost])
        return bool(ok), left, -(-retry_ms // 1000)  # round retry up to whole seconds

    async def settle(self, tenant: str, tpm: int, reserved: int, actual: int) -> int:
        return await self.settle_lua(keys=[f"rl:tok:{tenant}"], args=[tpm, reserved - actual])

    async def acquire_slot(self, tenant: str, max_conc: int, ttl_ms: int = 60_000):
        """Returns a slot id, or None if the tenant already has max_conc calls running."""
        slot = uuid.uuid4().hex
        ok = await self.acquire_lua(keys=[f"rl:conc:{tenant}"], args=[max_conc, slot, ttl_ms])
        return slot if ok else None

    async def release_slot(self, tenant: str, slot: str):
        await self.r.zrem(f"rl:conc:{tenant}", slot)
