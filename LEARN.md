# LEARN.md: what each feature teaches you

Read the code in this order. Each file is short on purpose.

## 1. Gateway (`app/main.py`)
1. Every LLM call enters here, so one place can enforce rules for everyone.
2. The whole flow is one function: key -> concurrency slot -> token reservation -> cache -> provider -> settle.
3. `try/finally` guarantees the concurrency slot is always released.
4. Redis errors become a fast 503 instead of a crash (see `chaos/RESULTS.md`, scenario 2).
5. Usage is written in a background task so the user does not wait for Postgres.

**Interview questions it prepares you for:** "Walk me through a request." "What happens when a dependency is down?" "Fail open or fail closed, and why?"

## 2. Rate limiting (`app/limiter.py`)
1. A token bucket refills over time; a call spends tokens, so bursts are allowed but averages are capped.
2. We *reserve* an estimate first, then *settle* with real usage (refund or charge). Over-use becomes debt that delays the next call.
3. Logic runs as Lua inside Redis, so it is atomic: 50 simultaneous requests cannot all slip through (tested).
4. Time comes from Redis (`TIME`), so gateway machines with different clocks still agree.
5. The concurrency cap is a sorted set of slots that expire on their own, so a crashed request cannot leak a slot.

**Questions:** "Design a rate limiter." "Why Lua? What is a race condition here?" "Token bucket vs sliding window vs fixed window?" "How do you rate-limit across several servers?"

## 3. Cache (`app/cache.py`)
1. Key = hash of tenant + request, so one tenant can never read another's answers.
2. A hit gets a full token refund: it cost nothing.
3. TTL stops stale answers living forever.
4. Limit: only exact repeats hit (no semantic matching).
5. Limit: concurrent identical requests all miss (no stampede protection yet).

**Questions:** "Cache invalidation?" "Cache stampede?" "What is safe to cache for an LLM?"

## 4. Job queue (`app/jobs_api.py`, `app/dispatcher.py`, `app/mq.py`, `app/worker.py`)
1. The API only saves the job in Postgres (`QUEUED`) and answers 202. Postgres is the source of truth; RabbitMQ only moves messages, so a broker outage never loses or rejects a job.
2. `Idempotency-Key` + a unique constraint means a retried POST never creates a duplicate.
3. The dispatcher publishes with publisher confirms ("it's on disk") and marks the job `DISPATCHED`; the worker acks only *after* saving the result.
4. Each message carries the job's `dispatch_seq`. A conditional `UPDATE ... WHERE dispatch_seq = <msg's>` means stale or duplicate messages are ignored (at-least-once delivery + idempotent processing = effectively once).
5. Retries use TTL queues that dead-letter back to the work queue (5s, 30s); the third failure goes to the DLQ.

**Questions:** "Exactly-once delivery?" "How do you avoid duplicate processing?" "Why a DB and a broker?" "What is a dead-letter queue?" "RabbitMQ vs Kafka?" "What is a fencing token?" (`dispatch_seq`)

## 5. Prompt optimisation (`app/optimiser.py`, `app/prompts_api.py`)
1. Prompt versions are immutable (a DB trigger refuses edits), so results are reproducible and rollbacks are trivial.
2. A golden set + an exact-match scorer turns "is this prompt good?" into a number.
3. The optimiser maximises savings subject to `score >= baseline - epsilon`.
4. The mock's quality is a hand-written function of prompt features. It proves the pipeline, not real-model quality. Prices are assumed.
5. Next step to make it real: swap the mock for a real model in eval mode and use a bigger golden set.

**Questions:** "How do you evaluate prompts?" "How would you roll out a prompt change safely?" "What are the limits of this evaluation?"

## 6. Postgres + auth (`app/db.py`, `app/auth.py`, `app/schema.sql`)
1. Only a SHA-256 hash of each API key is stored; a database leak does not leak keys.
2. A small in-process cache keeps Postgres out of the hot path; unknown keys are cached for 5s so guessing cannot hammer the DB.
3. Revoking a key publishes its hash on a Redis pub/sub channel; every gateway replica drops it from its own cache at once. The 60s TTL is only a backstop for a lost message.
4. Plain SQL with a tiny helper: easy to read, easy to explain.
5. `ON CONFLICT` is how idempotency and seeding stay safe to repeat.

**Questions:** "How do you store API keys?" "Caching vs consistency?" "How do you invalidate a local cache across many servers?" (pub/sub) "What if the invalidation message is lost?" (TTL backstop + clear on reconnect)

## 7. Failover + circuit breaker (`app/providers.py`)
1. Try provider A, then B.
2. After 3 failures in a row the breaker opens: stop calling A for 10s and fail fast.
3. After the cooldown, ONE probe call decides: success closes the breaker, failure reopens it.
4. If both are down: fast 503 with `Retry-After` instead of a hang.
5. The breaker state lives in Redis (`cb:A:tripped`, `cb:A:open` with a TTL = the cooldown, `cb:A:probe` set with NX so only ONE replica runs the half-open probe), so all replicas agree.

**Questions:** "What is a circuit breaker?" "How do you avoid a retry storm?" "Shared vs per-instance state, and what does sharing cost?" (an extra Redis call per request; if Redis is down we fail closed anyway)

## 8. Load test and chaos (`bench/`, `chaos/`)
1. k6 drives three scenarios at once; the report is generated from its raw output, never typed by hand.
2. Percentiles (p95/p99) matter more than averages because users feel the slow tail.
3. The load test found a real bottleneck: one worker drains jobs slower than they arrive (185s backlog). Three workers cut it to 16s.
4. Chaos tests were written with expectations *first*; two expectations failed on the first run and led to real fixes (worker reconnect, Redis 503).
5. Be honest about limits: one laptop, k6 on the same machine, short runs.

**Questions:** "How did you load test it, and what did you find?" "What broke and how did you fix it?" "What would you do with more time?"

## 9. UI (`web/`)
1. Five small pages, no state library, no component library.
2. The landing page reads `bench/results/stats.json` on the server, so its numbers can only be real or "not measured yet".
3. CORS must list the UI origin and *expose* the `X-*` headers, or the browser hides them from JavaScript.
4. The burst test makes the rate limiter visible: green, amber (cache hit), red (429).
5. A Playwright test drives the real stack in a real browser.

## 10. Running several copies (step 2)
1. Two gateways behind NGINX: the limiter, cache and breaker all live in Redis, so the copies agree. Test it with 50 simultaneous requests spread over both.
2. "Accuracy" of a limiter = over-admission %: tokens actually admitted vs the theoretical maximum (capacity + refill x time). Ours was slightly *under* the maximum.
3. A bug the chaos test found: an exception inside a background task *after* the response started breaks the kept-alive connection, so the NEXT request gets a 502. Background work must never raise.
4. CI runs the same tests against real Redis/RabbitMQ/Postgres service containers, so "works on my laptop" is checked.

**Questions:** "How do you scale a stateful-looking service horizontally?" "What breaks when you add a second replica?" "How do you measure a rate limiter's accuracy?"

## 11. Fair scheduling (step 3: `app/dispatcher.py`, `app/drr.py`)
1. Problem: with one shared FIFO queue a tenant that submits 10x more jobs makes everyone else wait behind its backlog (measured: p99 26 s for the victim).
2. Deficit Round Robin: walk a ring of tenants; each visit gives a tenant `weight` credits, one credit = one job. A big queue cannot take more than its share. The pointer stays on a tenant if the slots ran out mid-visit.
3. Backpressure: the dispatcher never lets more than `MAX_INFLIGHT` jobs be out in RabbitMQ/workers. The rest wait in Postgres, so the broker queue (a plain FIFO) stays short. Measured trade-off: 6 in flight -> victim p99 0.4 s, 50 in flight -> 4.4 s.
4. Leader election with a Postgres advisory lock: whoever holds the lock dispatches; if it dies its connection closes, the lock is released, and the standby takes over (0.31 s in our kill test). `SKIP LOCKED` + fenced claims keep even a brief double-leader harmless.
5. The reconciler repairs lost work: expired leases (dead worker) and `DISPATCHED` jobs whose message vanished go back to `QUEUED`. Interactive traffic beats batch for the shared provider budget because batch may only use a fraction of the slots.

**Questions:** "How do you stop one tenant from starving others?" "What is DRR?" "How do you do leader election without ZooKeeper?" "What is backpressure and where does it live in your design?" "What happens to in-flight work when the leader dies?"
