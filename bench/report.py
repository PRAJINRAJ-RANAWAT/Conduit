"""Turns bench/results/summary.json (k6 output) + DB counts into bench/results/REPORT.md."""
import json
from pathlib import Path
from app import db

import time
db.init()
out = Path(__file__).parent / "results"
m = json.loads((out / "summary.json").read_text())["metrics"]


def v(name, key):
    return m.get(name, {}).get("values", {}).get(key)


rows = []
for sc in ("capacity", "jobs", "limited"):
    d = f"http_req_duration{{scenario:{sc}}}"
    rows.append((sc, v(f"http_reqs{{scenario:{sc}}}", "count") or v(d, "count"),
                 v(d, "med"), v(d, "p(95)"), v(d, "p(99)")))
test_secs = 55  # length of the k6 scenarios
total = v("http_reqs", "count")
# The worker may still be busy: wait (up to 5 min) for every job to finish, and time it.
start = time.time()
while time.time() - start < 300:
    pending = db.run("SELECT count(*) AS n FROM jobs WHERE status IN ('QUEUED','RUNNING','RETRYING')")[0]["n"]
    if pending == 0:
        break
    time.sleep(2)
drain_secs = round(time.time() - start)
submitted = db.run("SELECT count(*) AS n FROM jobs")[0]["n"]
jobs = {r["status"]: r["n"] for r in db.run("SELECT status, count(*) AS n FROM jobs GROUP BY status")}
usage = db.run("SELECT count(*) AS n FROM usage")[0]["n"]
f = lambda x: "n/a" if x is None else f"{x:.1f}"
lines = ["# Load test results (measured)", "", (out / "hardware.txt").read_text().replace("\n", "  \n"), "",
         "| scenario | requests | req/s | p50 ms | p95 ms | p99 ms |", "|---|---|---|---|---|---|"]
lines += [f"| {s} | {int(c or 0)} | {(c or 0) / test_secs:.0f} | {f(a)} | {f(b)} | {f(c2)} |" for s, c, a, b, c2 in rows]
lines += ["",
          f"- Overall requests: {int(total)} in ~{test_secs}s -> **{total / test_secs:.0f} requests/s** (all scenarios together)",
          f"- 429 rate, capacity tenant (huge quota): {f(100 * (v('got_429{scenario:capacity}', 'rate') or 0))}%",
          f"- 429 rate, limited tenant (bob, 300 tokens/min): {f(100 * (v('got_429{scenario:limited}', 'rate') or 0))}%",
          f"- Cache hit rate, capacity tenant: {f(100 * (v('cache_hit{scenario:capacity}', 'rate') or 0))}%",
          f"- Unexpected HTTP errors (not 200/202/429): {f(100 * (v('http_req_failed', 'rate') or 0))}%",
          f"- Jobs submitted: {submitted}. After the load ended, the worker needed {drain_secs}s more to finish them"
          f" (still pending: {pending}). Final status counts: {jobs}",
          f"- Usage rows written: {usage}", "",
          "Reading this: `capacity` is closed-loop (50 users wait for each answer; the mock LLM sleeps 0.2s), so its req/s is bounded by that, "
          "not by the gateway. `limited` mostly measures fast 429 rejections. 55s runs on one laptop shared with k6.", "",
          "Raw data: `raw.json.gz` (every k6 data point), `summary.json` (k6 summary)."]
(out / "REPORT.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
