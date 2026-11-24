"""Two REAL gateway processes (replicas) sharing real Redis/Postgres. Proves state is shared, not per-process."""
import asyncio
import os
import subprocess
import sys
import time

import httpx
import pytest

from app import auth, db

R1, R2 = "http://localhost:8101", "http://localhost:8102"
ADMIN = {"X-Admin-Token": "dev-admin-token"}


@pytest.fixture(scope="module")
def replicas(mock_llm):
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                               "--log-level", "warning"], env=dict(os.environ)) for port in (8101, 8102)]
    end = time.time() + 20
    for url in (R1, R2):                                  # wait until both answer
        while time.time() < end:
            try:
                httpx.get(f"{url}/stats", timeout=1); break
            except httpx.HTTPError:
                time.sleep(0.3)
    if db.pool.closed:
        db.init()
    yield
    for p in procs:
        p.kill()


def chat(url, key, text):
    return httpx.post(f"{url}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=10,
                      json={"max_tokens": 5, "messages": [{"role": "user", "content": text}]})


def test_revoked_key_is_rejected_on_both_replicas_within_5s(replicas):
    auth.create_tenant("dave", 100_000, 10, "key-dave")
    for url in (R1, R2):                                  # both replicas now have the key cached
        assert chat(url, "key-dave", "hello").status_code == 200
    started = time.time()
    r = httpx.post(f"{R1}/admin/keys/revoke", json={"key": "key-dave"}, headers=ADMIN)
    assert r.status_code == 200
    for url in (R1, R2):
        while chat(url, "key-dave", f"again {time.time()}").status_code != 401:
            assert time.time() - started < 5, f"{url} still accepts the revoked key after 5s"
            time.sleep(0.05)
    print(f"revoked on both replicas after {time.time() - started:.2f}s")


def test_revoke_needs_admin_token(replicas):
    assert httpx.post(f"{R1}/admin/keys/revoke", json={"key": "key-alice"}).status_code == 403


def test_breaker_state_is_shared_between_replicas(replicas):
    import redis
    redis.Redis(db=1).flushdb()
    httpx.post("http://localhost:9100/admin/fail", json={"on": True})
    try:
        for i in range(3):                                # replica 1 alone sees A fail 3 times
            assert chat(R1, "key-alice", f"cb{i}").status_code == 200   # served by B
        # replica 2 never talked to A, yet knows its breaker is open
        assert httpx.get(f"{R2}/stats").json()["circuits"]["A"] == "open"
        assert chat(R2, "key-alice", "cb-x").headers["x-conduit-provider"] == "B"
    finally:
        httpx.post("http://localhost:9100/admin/fail", json={"on": False})


def test_50_simultaneous_requests_over_2_replicas_exactly_10_pass(replicas):
    import redis
    redis.Redis(db=1).flushdb()
    auth.create_tenant("erin", 100, 100, "key-erin")      # bucket 100 tokens; each request costs 10

    async def burst():
        async with httpx.AsyncClient(timeout=20) as c:
            calls = [c.post(f"{(R1, R2)[i % 2]}/v1/chat/completions",   # alternate replicas
                            headers={"Authorization": "Bearer key-erin"},
                            json={"max_tokens": 9, "messages": [{"role": "user", "content": f"q{i:02d}"}]})
                     for i in range(50)]
            return [r.status_code for r in await asyncio.gather(*calls)]

    codes = asyncio.run(burst())
    assert codes.count(200) == 10 and codes.count(429) == 40
