"""Needs Redis running: `docker compose up -d redis`."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import auth, main
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


async def test_token_limit_returns_429_with_headers(client):
    h = {"Authorization": "Bearer key-bob"}  # bob: 300 tokens/min
    big = {"messages": [{"role": "user", "content": "x" * 400}], "max_tokens": 100}  # ~201 each
    first = await client.post("/v1/chat/completions", json=big, headers=h)
    assert first.status_code == 200 and "X-RateLimit-Remaining-Tokens" in first.headers
    # first call refunded the unused part, so use fresh text to bypass the cache
    big2 = {"messages": [{"role": "user", "content": "y" * 400}], "max_tokens": 400}  # ~501 > 300
    second = await client.post("/v1/chat/completions", json=big2, headers=h)
    assert second.status_code == 429 and int(second.headers["Retry-After"]) >= 1
