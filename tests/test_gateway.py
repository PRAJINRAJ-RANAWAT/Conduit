"""Gateway tests: real Redis, Postgres and two real mock-LLM processes (see conftest.py)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import auth, db, main


@pytest.fixture
async def client(mock_llm):
    if db.pool.closed:
        db.init()
    auth.seed()
    await main.r.flushdb()
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
        yield c


BODY = {"messages": [{"role": "user", "content": "hi"}]}


async def test_bad_key_rejected(client):
    r = await client.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_second_identical_call_is_cached(client):
    h = {"Authorization": "Bearer key-alice"}
    first = await client.post("/v1/chat/completions", json=BODY, headers=h)
    second = await client.post("/v1/chat/completions", json=BODY, headers=h)
    assert first.headers["X-Conduit-Cache"] == "miss"
    assert second.headers["X-Conduit-Cache"] == "hit"


async def test_token_limit_returns_429_with_headers(client):
    h = {"Authorization": "Bearer key-bob"}  # bob: 300 tokens/min
    big = {"messages": [{"role": "user", "content": "x" * 400}], "max_tokens": 100}  # ~201 each
    first = await client.post("/v1/chat/completions", json=big, headers=h)
    assert first.status_code == 200 and "X-RateLimit-Remaining-Tokens" in first.headers
    # first call refunded the unused part, so use fresh text to bypass the cache
    big2 = {"messages": [{"role": "user", "content": "y" * 400}], "max_tokens": 400}  # ~501 > 300
    second = await client.post("/v1/chat/completions", json=big2, headers=h)
    assert second.status_code == 429 and int(second.headers["Retry-After"]) >= 1


async def test_50_simultaneous_requests_limit_10_exactly_10_pass(client):
    """Bucket = 100 tokens, each request costs 10 -> exactly 10 of 50 get through."""
    import asyncio
    auth.create_tenant("burst", 100, 100, "key-burst")
    h = {"Authorization": "Bearer key-burst"}
    calls = [client.post("/v1/chat/completions", headers=h, json={
        "max_tokens": 9, "messages": [{"role": "user", "content": f"q{i:02d}"}]}) for i in range(50)]
    codes = [r.status_code for r in await asyncio.gather(*calls)]
    assert codes.count(200) == 10 and codes.count(429) == 40


async def test_concurrency_cap_returns_429(client):
    """bob may run 2 calls at once; the others in a burst of 5 are refused."""
    import asyncio
    h = {"Authorization": "Bearer key-bob"}
    calls = [client.post("/v1/chat/completions", headers=h, json={
        "max_tokens": 2, "messages": [{"role": "user", "content": f"c{i}"}]}) for i in range(5)]
    codes = sorted(r.status_code for r in await asyncio.gather(*calls))
    assert codes == [200, 200, 429, 429, 429]


async def test_usage_is_recorded_in_postgres(client):
    import asyncio
    db.run("DELETE FROM usage")
    await client.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer key-alice"})
    await asyncio.sleep(0.3)
    row = db.run("SELECT tenant, provider FROM usage")[0]
    assert row == {"tenant": "alice", "provider": "A"}


async def test_revoked_key_is_rejected_after_cache_expires(client):
    auth.create_tenant("carol", 1000, 2, "key-carol")
    h = {"Authorization": "Bearer key-carol"}
    assert (await client.post("/v1/chat/completions", json=BODY, headers=h)).status_code == 200
    db.run("UPDATE api_keys SET revoked=true WHERE tenant='carol'")
    auth._cache.clear()                      # same as waiting out the 30s cache
    assert (await client.post("/v1/chat/completions", json=BODY, headers=h)).status_code == 401
