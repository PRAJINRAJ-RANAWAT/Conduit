"""Limiter accuracy across 2 gateway replicas (traffic goes through NGINX on :8080).

Test 1: 50 simultaneous requests, budget for exactly 10 -> how many pass? (run 3 times)
Test 2: a tenant with X tokens/minute, 100 concurrent clients hammering for 30s.
        admitted tokens = sum of the REAL usage reported in every 200 response.
        theoretical max = X (bucket starts full) + X/60 * elapsed seconds.
        over-admission % = (admitted - max) / max * 100   (negative = the limiter admitted less than the max)
Usage:  PYTHONPATH=. .venv/bin/python bench/accuracy.py
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx

from app import auth, db

URL = "http://localhost:8080/v1/chat/completions"
OUT = Path(__file__).parent / "results" / "accuracy"


async def one(client, key, text, max_tokens):
    r = await client.post(URL, headers={"Authorization": f"Bearer {key}"}, json={
        "max_tokens": max_tokens, "messages": [{"role": "user", "content": text}]})
    return r


async def test1():
    tenant, key = f"acc1-{uuid.uuid4().hex[:6]}", f"key-{uuid.uuid4().hex}"
    auth.create_tenant(tenant, 100, 100, key)         # 100 tokens; each request below costs 10
    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=100)) as c:
        rs = await asyncio.gather(*[one(c, key, f"q{i:02d}", 9) for i in range(50)])
    codes = [r.status_code for r in rs]
    return {"passed": codes.count(200), "rejected_429": codes.count(429), "other": len(codes) - codes.count(200) - codes.count(429)}


async def test2(tpm=6000, clients=100, seconds=30):
    tenant, key = f"acc2-{uuid.uuid4().hex[:6]}", f"key-{uuid.uuid4().hex}"
    auth.create_tenant(tenant, tpm, 1000, key)
    admitted, n200, n429, stop = 0, 0, 0, time.time() + seconds
    start = time.time()

    async def client_loop(c, cid):
        nonlocal admitted, n200, n429
        i = 0
        while time.time() < stop:
            r = await one(c, key, f"c{cid}-{i}-{uuid.uuid4().hex[:6]}", 20)   # unique prompt: never a cache hit
            i += 1
            if r.status_code == 200:
                u = r.json()["usage"]
                admitted += u["prompt_tokens"] + u["completion_tokens"]
                n200 += 1
            else:
                n429 += 1
                await asyncio.sleep(0.05)           # tiny pause so 429 loops do not spin the CPU

    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=clients)) as c:
        await asyncio.gather(*[client_loop(c, k) for k in range(clients)])
    elapsed = time.time() - start
    theoretical = tpm + tpm / 60 * elapsed
    return {"tokens_per_minute": tpm, "clients": clients, "elapsed_s": round(elapsed, 1), "responses_200": n200,
            "responses_429": n429, "admitted_tokens": admitted, "theoretical_max_tokens": round(theoretical),
            "over_admission_pct": round(100 * (admitted - theoretical) / theoretical, 2)}


async def main():
    db.init()
    res = {"test1_50_simultaneous_limit_10": [await test1() for _ in range(3)],
           "test2_token_accuracy": [await test2() for _ in range(3)]}
    (OUT / "accuracy.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))

asyncio.run(main())
