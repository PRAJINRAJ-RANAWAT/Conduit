# Noisy-neighbour results (measured)

B floods 20 jobs/s, A submits 2 jobs/s, for 40s; 3 workers (~12 jobs/s total capacity), 2 dispatchers, mock LLM 0.2s.
One laptop. fifo-inflight6 and fair-inflight6 each ran twice (the two runs agree closely); fair-inflight50 ran once.

| config | A jobs | A time-to-start p50 / p95 / p99 (ms) | A completion p50 / p95 / p99 (ms) |
|---|---|---|---|
| fifo-inflight6-run1 | 80/80 | 13412.5 / 25392.3 / 26341.5 | 13627.0 / 25610.4 / 26572.9 |
| fair-inflight6-run2 | 80/80 | 218.5 / 379.1 / 404.1 | 442.3 / 606.6 / 643.1 |
| fair-inflight50-run3 | 80/80 | 3344.4 / 4283.0 / 4436.9 | 3567.7 / 4494.6 / 4648.1 |
| fifo-inflight6-run4 | 80/80 | 13548.7 / 24892.2 / 26030.1 | 13768.3 / 25114.8 / 26251.3 |
| fair-inflight6-run5 | 80/80 | 214.4 / 368.8 / 420.4 | 430.7 / 621.3 / 687.6 |
