"""Stop Postgres (tenants, keys, jobs and usage live there).
EXPECTED: - chat with a key the gateways already have cached: still HTTP 200 (usage rows are lost, not the answer)
          - chat with a key no gateway has seen: fast 503 (cannot look it up), not a hang
          - POST /jobs: fast 503 (cannot save the job), not a hang
          - after Postgres returns, with NO restarts: all of the above work again, and a job finishes.
"""
import sys

sys.path.insert(0, "..")
from lib import *

from app import auth, db

db.init()
auth.create_tenant("pgtest", 100_000, 10, f"key-pgtest-{RUN}")      # never used yet -> not cached anywhere
NEW = {"Authorization": f"Bearer key-pgtest-{RUN}"}

def timed_chat(headers, text):
    t = time.time()
    try:
        r = httpx.post(f"{G}/v1/chat/completions", headers=headers, timeout=15,
                       json={"max_tokens": 5, "messages": [{"role": "user", "content": text}]})
        return r.status_code, time.time() - t
    except Exception as e:
        return type(e).__name__, time.time() - t

for i in range(6):                                   # warm both gateway replicas' key cache
    assert chat(f"pg-warm-{RUN}-{i}").status_code == 200
dc("stop", "postgres"); say("postgres stopped")
cached = [timed_chat(H, f"pg-c-{RUN}-{i}") for i in range(6)]
say("chat, cached key (6 calls, both replicas): " + str([c for c, _ in cached]))
unc, unc_s = timed_chat(NEW, f"pg-u-{RUN}"); say(f"chat, uncached key: {unc} after {unc_s:.1f}s")
t = time.time()
try:
    r = httpx.post(f"{G}/jobs", headers={**H, "Idempotency-Key": f"{RUN}-pg"}, json={"prompt": "pg"}, timeout=15)
    job_status = r.status_code
except Exception as e:
    job_status = type(e).__name__
job_s = time.time() - t; say(f"POST /jobs: {job_status} after {job_s:.1f}s")

dc("start", "postgres"); say("postgres started; waiting for healthy")
wait_until(lambda: "healthy" in dc("ps", "postgres"), 60, every=2)
chat_back = wait_until(lambda: timed_chat(NEW, f"pg-u2-{RUN}")[0] == 200, 40, every=2)
say(f"uncached-key chat works again: {chat_back}")
job_ok = None
for _ in range(10):
    key, r = submit(7)
    if r.status_code in (200, 202):
        job_ok = r.json()["id"]; break
    time.sleep(2)
done = bool(job_ok) and wait_until(lambda: any(j["id"] == job_ok and j["status"] == "SUCCEEDED" for j in jobs()), 40)
say(f"job created and finished after recovery: {done}")
verdict(all(c == 200 for c, _ in cached) and unc == 503 and unc_s < 5 and job_status == 503 and job_s < 5
        and chat_back and done,
        f"cached_ok={all(c == 200 for c, _ in cached)}, uncached={unc}({unc_s:.1f}s), jobs={job_status}({job_s:.1f}s), "
        f"recovered={chat_back and done}")
