"""Kill -9 the ACTIVE dispatcher in the middle of a 5,000-job batch.
EXPECTED: the standby dispatcher takes the Postgres advisory lock within a few seconds (it polls every 1s, and the lock is
          released the moment the dead process's connection closes). All 5,000 jobs end SUCCEEDED (0 lost) and none runs twice
          (every job has attempts == 1; no failures were injected, so attempts > 1 would mean a duplicate execution).
Setup: mock LLM latency 0.01s and 6 workers so 5,000 jobs finish in about a minute (restored afterwards).
"""
import asyncio
import subprocess
import sys
import os
sys.path.insert(0, "..")
from lib import *
from app import auth, db

N = 5000
env = {**os.environ, "MOCK_LATENCY": "0.01", "WORKERS": "6"}
subprocess.run(["docker", "compose", "up", "-d", "mock-a", "mock-b"], env=env, capture_output=True)
subprocess.run(["docker", "compose", "up", "-d", "--scale", "worker=6", "worker", "dispatcher"], env=env, capture_output=True)
db.init(); db.run("TRUNCATE jobs")
key = f"key-batch-{RUN}"; auth.create_tenant("batch-t", 10**9, 1000, key)
LEADER = "SELECT a.application_name AS host FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE l.locktype='advisory' AND l.objid=4242 AND l.granted"
counts = lambda: {r["status"]: r["n"] for r in db.run("SELECT status, count(*) AS n FROM jobs GROUP BY status")}
wait_until(lambda: db.run(LEADER), 30)

async def submit_all():
    sem = asyncio.Semaphore(50)
    async with httpx.AsyncClient(timeout=30) as c:
        async def one(i):
            async with sem:
                r = await c.post(f"{G}/jobs", headers={"Authorization": f"Bearer {key}", "Idempotency-Key": f"{RUN}-{i}"}, json={"prompt": f"b{i}"})
                return r.status_code
        return await asyncio.gather(*[one(i) for i in range(N)])

t_submit = time.time()
async def kill_when_midway():
    while counts().get("SUCCEEDED", 0) < 1000:
        await asyncio.sleep(0.2)
    leader = db.run(LEADER)[0]["host"]
    t0 = time.time()
    subprocess.run(["docker", "kill", "-s", "KILL", leader], capture_output=True)
    say(f"killed dispatcher {leader} at {counts()}")
    while True:
        h = db.run(LEADER)
        if h and h[0]["host"] != leader:
            return leader, h[0]["host"], time.time() - t0
        await asyncio.sleep(0.05)
async def main():
    return await asyncio.gather(submit_all(), kill_when_midway())
codes, (old, new, takeover) = asyncio.run(main())
say(f"submitted {N} jobs in {time.time() - t_submit:.0f}s (HTTP codes: {sorted(set(codes))})")
say(f"standby {new} became leader {takeover:.2f}s after {old} was killed")
done = wait_until(lambda: counts().get("SUCCEEDED", 0) == N, 300, every=2)
c = counts(); rows = db.run("SELECT max(attempts) AS mx, sum(attempts) AS total, count(*) AS n FROM jobs")[0]
say(f"final counts: {c}; attempts: max={rows['mx']} total={rows['total']} for {rows['n']} jobs")
subprocess.run(["docker", "compose", "up", "-d", "mock-a", "mock-b"], env={**os.environ, "MOCK_LATENCY": "0.2"}, capture_output=True)
subprocess.run(["docker", "compose", "up", "-d", "--scale", "worker=3", "worker", "dispatcher"], env={**os.environ, "WORKERS": "3"}, capture_output=True)
verdict(done and c == {"SUCCEEDED": N} and rows["mx"] == 1 and rows["total"] == N and takeover < 10,
        f"takeover={takeover:.2f}s, succeeded={c.get('SUCCEEDED', 0)}/{N}, lost={N - c.get('SUCCEEDED', 0)}, duplicate_executions={rows['total'] - N}")
