# Step 2 measurements (all from files in this folder)

## Workers: backlog drain time after the load ends (k6 load, 1,101 jobs submitted, 0 lost in every run)
| run | topology | drain time | source |
|---|---|---|---|
| original | 1 gateway, 1 worker, no NGINX | **185 s** | `original-1gw-1worker/REPORT.md` |
| 2gw-1worker | 2 gateways behind NGINX, 1 worker | **181 s** | `2gw-1worker/REPORT.md` |
| 2gw-3workers | 2 gateways behind NGINX, 3 workers | **16 s** | `2gw-3workers/REPORT.md` |

Same laptop, k6 on the same machine. Going from 1 to 3 workers cut the drain time by ~11x in this run (more than 3x because the
single worker had also been competing with the gateways for CPU while the load was still running).
That explanation is my reading, not something I separately measured: ESTIMATE.

## Limiter accuracy across replicas (NGINX -> 2 gateways; `accuracy/accuracy.json`, script `bench/accuracy.py`)
- 50 simultaneous requests, budget for exactly 10: **10 passed, 40 got 429, in all 3 runs**.
- Token test, 6,000 tokens/minute, 100 concurrent clients for ~30s, 3 runs: admitted tokens vs theoretical maximum
  (6,000 + 100/s x elapsed): **over-admission -0.55%, -0.62%, -0.62%** (negative = it admitted slightly *less* than the maximum; it never exceeded it).
  The same 10-of-50 check also passes as an automated test with two real gateway processes (`tests/test_replicas.py`).

## Revocation and breaker (automated tests, `tests/test_replicas.py`, two real gateway processes)
- Revoking a key is rejected on **both** replicas; the test allows 5s and printed **0.03s** on the run I looked at (a single run, not a distribution).
- Circuit breaker: 3 failures seen only by replica 1 -> replica 2 reports provider A "open" and routes to B without ever having called A.
