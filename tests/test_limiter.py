"""Limiter tests against REAL Redis."""
import asyncio

import redis.asyncio as redis

from app.limiter import Limiter

r = redis.from_url("redis://localhost:6379/1", decode_responses=True)
lim = Limiter(r)


async def test_50_concurrent_reserves_exactly_10_pass():
    await r.flushdb()
    # bucket of 100 tokens, each call costs 10 -> exactly 10 fit
    results = await asyncio.gather(*[lim.reserve("t", 100, 10) for _ in range(50)])
    assert sum(ok for ok, _, _ in results) == 10


async def test_settle_refunds_and_charges():
    await r.flushdb()
    await lim.reserve("t", 1000, 400)               # bucket now ~600
    assert await lim.settle("t", 1000, 400, 100) >= 890   # used less: refund 300 -> ~900
    left = await lim.settle("t", 1000, 100, 1500)   # used way more: charge 1400 -> debt
    assert left < 0
    ok, _, retry = await lim.reserve("t", 1000, 10)
    assert not ok and retry >= 1                    # in debt -> must wait


async def test_concurrency_cap_and_slot_expiry():
    await r.flushdb()
    a = await lim.acquire_slot("t", 2, ttl_ms=300)
    b = await lim.acquire_slot("t", 2, ttl_ms=300)
    assert a and b and await lim.acquire_slot("t", 2) is None   # third refused
    await asyncio.sleep(0.4)                                    # slots expire by themselves
    assert await lim.acquire_slot("t", 2) is not None
    await lim.release_slot("t", a)
