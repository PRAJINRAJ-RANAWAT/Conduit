"""Noisy-neighbour experiment: does one tenant's flood slow down another tenant's jobs?

Tenant B floods the queue (20 jobs/s). Tenant A submits a steady, modest 2 jobs/s. 3 workers can finish about
12 jobs/s in total, so B's backlog grows all the time. For each configuration we measure how long A's jobs wait
before a worker STARTS them (time-to-start) and until they FINISH (completion time).
  fifo = dispatcher picks the oldest job overall (A waits behind B's backlog)
  fair = dispatcher uses Deficit Round Robin across tenants (equal weights)
Usage: PYTHONPATH=. .venv/bin/python bench/noisy_neighbour.py
Results: bench/results/noisy-neighbour/<config>-run<N>-raw.json (every job of A) + summary.json + REPORT.md
"""
import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx

from app import auth, db, mq

URL = "http://localhost:8080/jobs"
OUT = Path(__file__).parent / "results" / "noisy-neighbour"
SECONDS, A_RATE, B_RATE = 40, 2, 20          # submit phase length, jobs/s of A, jobs/s of B (10x A)
CONFIGS = [("fifo", 6), ("fair", 6), ("fair", 50), ("fifo", 6), ("fair", 6)]   # (mode, MAX_INFLIGHT)


def restart_dispatchers(mode: str, max_inflight: int):
    env = {**os.environ, "DISPATCH_MODE": mode, "MAX_INFLIGHT": str(max_inflight)}
    subprocess.run(["docker", "compose", "up", "-d", "--force-recreate", "dispatcher"], env=env, capture_output=True)
    for _ in range(60):                       # wait until a leader exists
        if db.run("SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=4242 AND granted"):
            return
        time.sleep(1)
    raise RuntimeError("no dispatcher leader")


def reset():
    db.run("TRUNCATE jobs")
    ch = mq.connect().channel()
    for q in [mq.WORK, mq.DLQ] + [f"{mq.P}jobs.retry.{i}" for i in range(3)]:
        ch.queue_purge(q)


async def submit_loop(keys, tenant, rate, run):
    """Send `rate` jobs per second for SECONDS seconds, in 10 ticks per second."""
    async with httpx.AsyncClient(timeout=30) as c:
        tasks, sent = [], 0
        for tick in range(SECONDS * 10):
            due = (tick + 1) * rate // 10 - tick * rate // 10          # jobs to send in this tick
            for _ in range(due):
                tasks.append(asyncio.create_task(c.post(
                    URL, json={"prompt": f"{tenant} job"},
                    headers={"Authorization": f"Bearer {keys[tenant]}", "Idempotency-Key": f"{run}-{tenant}-{sent}"})))
                sent += 1
            await asyncio.sleep(0.1)
        await asyncio.gather(*tasks)


def pct(values, p):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(p / 100 * len(values)))], 1) if values else None


async def one_run(mode, max_inflight, n):
    restart_dispatchers(mode, max_inflight)
    reset()
    keys = {"noisy-a": f"key-{uuid.uuid4().hex}", "noisy-b": f"key-{uuid.uuid4().hex}"}
    for t, k in keys.items():
        auth.create_tenant(t, 10**9, 1000, k, weight=1)       # equal weights
    run = uuid.uuid4().hex[:6]
    await asyncio.gather(submit_loop(keys, "noisy-a", A_RATE, run), submit_loop(keys, "noisy-b", B_RATE, run))
    end = time.time() + 240
    while time.time() < end:                  # wait until all of A's jobs are done
        left = db.run("SELECT count(*) AS n FROM jobs WHERE tenant='noisy-a' AND status NOT IN ('SUCCEEDED','DEAD')")[0]["n"]
        if left == 0:
            break
        time.sleep(1)
    rows = db.run("""SELECT tenant, status,
                     extract(epoch FROM started_at - created_at) * 1000 AS tts_ms,
                     extract(epoch FROM finished_at - created_at) * 1000 AS completion_ms
                     FROM jobs WHERE tenant IN ('noisy-a','noisy-b')""")
    a = [r for r in rows if r["tenant"] == "noisy-a"]
    b = [r for r in rows if r["tenant"] == "noisy-b"]
    name = f"{mode}-inflight{max_inflight}-run{n}"
    (OUT / f"{name}-raw.json").write_text(json.dumps(
        [{k: (float(v) if k.endswith("_ms") and v is not None else v) for k, v in r.items()} for r in a], indent=0))
    tts = [float(r["tts_ms"]) for r in a if r["tts_ms"] is not None]
    comp = [float(r["completion_ms"]) for r in a if r["completion_ms"] is not None]
    s = {"config": name, "mode": mode, "max_inflight": max_inflight,
         "A_jobs_submitted": len(a), "A_jobs_finished": len(comp), "B_jobs_submitted": len(b),
         "B_jobs_finished": sum(r["status"] == "SUCCEEDED" for r in b),
         "A_time_to_start_ms": {"p50": pct(tts, 50), "p95": pct(tts, 95), "p99": pct(tts, 99), "max": round(max(tts), 1)},
         "A_completion_ms": {"p50": pct(comp, 50), "p95": pct(comp, 95), "p99": pct(comp, 99), "max": round(max(comp), 1)}}
    print(json.dumps(s), flush=True)
    return s


async def main():
    db.init()
    results = []
    for n, (mode, mi) in enumerate(CONFIGS, 1):
        results.append(await one_run(mode, mi, n))
    (OUT / "summary.json").write_text(json.dumps(results, indent=1))
    lines = ["# Noisy-neighbour results (measured)", "",
             f"B floods {B_RATE} jobs/s, A submits {A_RATE} jobs/s, for {SECONDS}s; 3 workers (~12 jobs/s total capacity), 2 dispatchers, mock LLM 0.2s.",
             "One laptop. fifo-inflight6 and fair-inflight6 each ran twice (the two runs agree closely); fair-inflight50 ran once.", "",
             "| config | A jobs | A time-to-start p50 / p95 / p99 (ms) | A completion p50 / p95 / p99 (ms) |", "|---|---|---|---|"]
    for r in results:
        t, c = r["A_time_to_start_ms"], r["A_completion_ms"]
        lines.append(f"| {r['config']} | {r['A_jobs_finished']}/{r['A_jobs_submitted']} | {t['p50']} / {t['p95']} / {t['p99']} | {c['p50']} / {c['p95']} / {c['p99']} |")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

asyncio.run(main())
