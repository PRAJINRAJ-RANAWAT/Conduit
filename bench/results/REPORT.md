# Load test results (measured)

date: 2026-11-24T06:15:15Z  
cpu: Apple M2 (8 cores)  
ram: 8 GB  
docker VM memory: 4108828672  
gateway: 1 uvicorn process, 1 worker process, mock LLM A/B (0.2s sleep), Redis/RabbitMQ/Postgres in Docker  


| scenario | requests | req/s | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| capacity | 14239 | 259 | 219.6 | 260.2 | 295.3 |
| jobs | 1101 | 20 | 8.2 | 25.9 | 48.5 |
| limited | 31530 | 573 | 3.0 | 14.6 | 28.0 |

- Overall requests: 46870 in ~55s -> **852 requests/s** (all scenarios together)
- 429 rate, capacity tenant (huge quota): 0.0%
- 429 rate, limited tenant (bob, 300 tokens/min): 99.9%
- Cache hit rate, capacity tenant: 30.2%
- Unexpected HTTP errors (not 200/202/429): 0.0%
- Jobs submitted: 1101. After the load ended, the worker needed 185s more to finish them (still pending: 0). Final status counts: {'SUCCEEDED': 1101}
- Usage rows written: 14282

Reading this: `capacity` is closed-loop (50 users wait for each answer; the mock LLM sleeps 0.2s), so its req/s is bounded by that, not by the gateway. `limited` mostly measures fast 429 rejections. 55s runs on one laptop shared with k6.

Raw data: `raw.json.gz` (every k6 data point), `summary.json` (k6 summary).
