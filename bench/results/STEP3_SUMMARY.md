# Step 3 measurements (all from files in this folder)

## Noisy neighbour: tenant B floods 20 jobs/s, tenant A submits a steady 2 jobs/s (40 s; 3 workers ~ 12 jobs/s total capacity)
Source: `noisy-neighbour/REPORT.md`, raw per-job data in `noisy-neighbour/*-raw.json`, script `bench/noisy_neighbour.py`.
A's jobs: time until a worker STARTS them (time-to-start), p50 / p95 / p99:

| dispatcher | max in flight | run | p50 | p95 | p99 |
|---|---|---|---|---|---|
| FIFO (oldest first) | 6 | 1 | 13.4 s | 25.4 s | 26.3 s |
| FIFO (oldest first) | 6 | 2 | 13.5 s | 24.9 s | 26.0 s |
| fair (DRR) | 6 | 1 | 0.22 s | 0.38 s | 0.40 s |
| fair (DRR) | 6 | 2 | 0.21 s | 0.37 s | 0.42 s |
| fair (DRR) | 50 | 1 | 3.3 s | 4.3 s | 4.4 s |

All 80 of A's jobs finished in every run. Reading it: with FIFO, A's jobs queue behind B's whole backlog. With the fair dispatcher they jump ahead.
`max in flight` matters: the broker is a plain FIFO queue, so every job already sent to RabbitMQ is in line ahead of A's next job. With 6 in flight A waits behind
at most a few jobs; with 50 it waits behind up to 50 (about 4 s at 12 jobs/s). The price of a small number is that the workers could run out of work
if the dispatcher falls behind; with 3 workers, 6 was enough to keep them busy in this run (B's backlog never drained during the test) but I did not measure
utilisation separately.
Completion time (start -> finish) is in the report: it is the time-to-start plus about 0.2 s of work.

## Dispatcher failover (`chaos/RESULTS.md`, scenario 6)
Killed the active dispatcher with `kill -9` during a 5,000-job batch: standby leader after **0.31 s** (one run), 5,000/5,000 SUCCEEDED, 0 lost, 0 duplicates.
