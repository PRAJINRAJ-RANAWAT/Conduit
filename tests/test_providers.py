"""Fallback + circuit breaker, against two real mock providers (A :9100, B :9101)."""
import asyncio
import httpx
import pytest

from app import auth, db, main, providers
from httpx import ASGITransport, AsyncClient

H = {"Authorization": "Bearer key-alice"}


def set_fail(port: int, on: bool):
    httpx.post(f"http://localhost:{port}/admin/fail", json={"on": on})


@pytest.fixture
async def client(mock_llm):
    if db.pool.closed:
        db.init()
    auth.seed()
    await main.r.flushdb()
    for b in providers.breakers.values():
        b.success()
    yield AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t")
    set_fail(9100, False); set_fail(9101, False)


async def ask(client, n):
    return await client.post("/v1/chat/completions", headers=H,
                             json={"messages": [{"role": "user", "content": f"p{n}"}]})


async def test_falls_back_to_B_when_A_is_down_and_breaker_opens(client):
    set_fail(9100, True)
    async with client:
        for i in range(4):
            r = await ask(client, i)
            assert r.status_code == 200 and r.headers["X-Conduit-Provider"] == "B"
    assert providers.breakers["A"].state == "open"       # 3 failures in a row -> open


async def test_breaker_recovers_through_half_open_probe(client):
    set_fail(9100, True)
    async with client:
        for i in range(3):
            await ask(client, i)
        assert providers.breakers["A"].state == "open"
        set_fail(9100, False)                             # A is healthy again
        await asyncio.sleep(1.2)                          # cooldown (1s in tests) passes
        r = await ask(client, 99)                         # the half-open probe goes to A
        assert r.headers["X-Conduit-Provider"] == "A"
    assert providers.breakers["A"].state == "closed"


async def test_both_down_gives_fast_503_with_retry_after(client):
    set_fail(9100, True); set_fail(9101, True)
    async with client:
        r = await ask(client, 1)
    assert r.status_code == 503 and r.headers["Retry-After"] == "10"
