# Load test results (measured)

date: 2026-11-24T06:40:33Z  
cpu: Apple M2 (8 cores)  
ram: 8 GB  
docker VM memory: 4108828672  
topology: 2 gateways behind nginx, 3 workers  
worker containers running: 3  
gateway containers running: 2  
mock LLM A/B: 0.2s sleep; Redis/RabbitMQ/Postgres in Docker  


| scenario | requests | req/s | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| capacity | 14908 | 271 | 210.3 | 244.9 | 309.1 |
| jobs | 1101 | 20 | 8.4 | 36.7 | 89.0 |
| limited | 42023 | 764 | 2.4 | 9.7 | 21.3 |

- Overall requests: 58032 in ~55s -> **1055 requests/s** (all scenarios together)
- 429 rate, capacity tenant (huge quota): 0.0%
- 429 rate, limited tenant (bob, 300 tokens/min): 99.9%
- Cache hit rate, capacity tenant: 29.4%
- Unexpected HTTP errors (not 200/202/429): 0.0%
- Jobs submitted: 1101. After the load ended, the worker needed 16s more to finish them (still pending: 0). Final status counts: {'SUCCEEDED': 1101}
- Usage rows written: 14951

Reading this: `capacity` is closed-loop (50 users wait for each answer; the mock LLM sleeps 0.2s), so its req/s is bounded by that, not by the gateway. `limited` mostly measures fast 429 rejections. 55s runs on one laptop shared with k6.

Raw data: `raw.json.gz` (every k6 data point), `summary.json` (k6 summary).
