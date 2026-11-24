"""Make provider A fail.
EXPECTED: chat keeps answering (HTTP 200) from provider B, the breaker for A opens after 3 failures, and when A is
          healthy again the half-open probe brings it back. If BOTH fail: fast 503 + Retry-After.
"""
from lib import *

def which(i):
    r = chat(f"p-{RUN}-{i}"); return r.status_code, r.headers.get("x-conduit-provider")

def fail(port, on):
    httpx.post(f"http://localhost:{port}/admin/fail", json={"on": on})

say("A healthy: " + str(which(0)))
fail(9000, True); seen = [which(i) for i in range(1, 6)]; say("A down: " + str(seen))
fail(9001, True); t = time.time(); both = chat(f"p-{RUN}-9"); secs = time.time() - t
say(f"A and B down: HTTP {both.status_code}, Retry-After={both.headers.get('retry-after')}, in {secs:.2f}s")
fail(9001, False); fail(9000, False); say("A and B healthy again; waiting 11s for the breaker cooldown"); time.sleep(11)
after = [which(i) for i in range(10, 13)]; say("after recovery: " + str(after))
verdict(all(c == 200 and p == "B" for c, p in seen) and both.status_code == 503 and secs < 5
        and all(p == "A" for _, p in after), "failover to B, fast 503 when both down, A restored")
