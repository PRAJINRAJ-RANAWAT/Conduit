"""Needs Redis running: `docker compose up -d redis`."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.mock_provider import app as provider_app


@pytest.fixture
async def client(monkeypatch):
    await main.r.flushdb()
    # Route the gateway's outgoing LLM call straight into the in-process mock.
    real = main.httpx.AsyncClient
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda **kw: real(transport=ASGITransport(app=provider_app), base_url="http://p"),
    )
    monkeypatch.setattr(main, "PROVIDER_URL", "http://p")
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


async def test_concurrent_requests_exactly_limit_pass(client):
    """50 simultaneous requests, limit 10 -> exactly 10 get through (Redis INCR is atomic)."""
    import asyncio
    main.TENANTS["key-burst"] = {"name": "burst", "rpm": 10}
    h = {"Authorization": "Bearer key-burst"}
    # distinct prompts so the cache can't answer any of them
    calls = [client.post("/v1/chat/completions", headers=h,
             json={"messages": [{"role": "user", "content": f"q{i}"}]}) for i in range(50)]
    codes = [r.status_code for r in await asyncio.gather(*calls)]
    assert codes.count(200) == 10 and codes.count(429) == 40


async def test_rate_limit(client):
    h = {"Authorization": "Bearer key-bob"}  # bob: 5 per minute
    codes = [(await client.post("/v1/chat/completions", json=BODY, headers=h)).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
