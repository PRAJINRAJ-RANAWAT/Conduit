# Load test results (measured)

date: 2026-11-24T05:57:34Z  
cpu: Apple M2 (8 cores)  
ram: 8 GB  
docker VM memory: 4108828672  
gateway: 1 uvicorn process, 1 worker process, mock LLM A/B (0.2s sleep), Redis/RabbitMQ/Postgres in Docker  


| scenario | requests | req/s | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| capacity | 13319 | 242 | 222.2 | 296.9 | 402.2 |
| jobs | 1101 | 20 | 8.7 | 45.3 | 107.3 |
| limited | 27020 | 491 | 3.4 | 17.6 | 38.5 |

- Overall requests: 41440 in ~55s -> **753 requests/s** (all scenarios together)
- 429 rate, capacity tenant (huge quota): 0.0%
- 429 rate, limited tenant (bob, 300 tokens/min): 99.8%
- Cache hit rate, capacity tenant: 30.2%
- Unexpected HTTP errors (not 200/202/429): 0.0%
- Jobs submitted: 1101. After the load ended, the worker needed 0s more to finish them (still pending: 0). Final status counts: {'SUCCEEDED': 1101}
- Usage rows written: 13362

Reading this: `capacity` is closed-loop (50 users wait for each answer; the mock LLM sleeps 0.2s), so its req/s is bounded by that, not by the gateway. `limited` mostly measures fast 429 rejections. 55s runs on one laptop shared with k6.

Raw data: `raw.json.gz` (every k6 data point), `summary.json` (k6 summary).
