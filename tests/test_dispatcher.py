"""Dispatcher tests: DRR maths, in-flight cap, leader election + failover, reconciler, provider priority.
Everything except the DRR unit tests uses REAL Postgres/RabbitMQ/Redis and real dispatcher/worker processes."""
import time

import pytest

from app import db, mq
from app.drr import DRR
from app.provider_budget import SyncBudget, limit_for
from conftest import start


# ---------- DRR (pure logic, fast) ----------
def test_drr_small_tenant_is_not_starved_by_a_flood():
    got = DRR().allocate({"a": 1, "b": 1000}, {"a": 1, "b": 1}, capacity=10)
    assert got == {"a": 1, "b": 9}              # A gets its 1 job out although B has 1000 queued


def test_drr_respects_weights_even_with_one_slot_per_call():
    drr, total = DRR(), {"a": 0, "b": 0}
    for _ in range(80):                          # tiny capacity each round: the pointer must persist
        for t, n in drr.allocate({"a": 500, "b": 500}, {"a": 1, "b": 3}, capacity=1).items():
            total[t] += n
    assert total == {"a": 20, "b": 60}           # exactly 1:3


def test_drr_never_exceeds_capacity_or_queue():
    got = DRR().allocate({"a": 3, "b": 2}, {"a": 5, "b": 5}, capacity=100)
    assert got == {"a": 3, "b": 2}


# ---------- integration ----------
@pytest.fixture(autouse=True)
def clean(mock_llm):
    if db.pool.closed:
        db.init()
    db.run("TRUNCATE jobs")
    ch = mq.connect().channel()
    mq.declare(ch)
    for q in [mq.WORK, mq.DLQ] + [f"{mq.P}jobs.retry.{i}" for i in range(3)]:
        ch.queue_purge(q)
    yield


def add_jobs(tenant, n, **cols):
    for i in range(n):
        db.run("INSERT INTO jobs (tenant, idem_key, prompt, work_secs) VALUES (%s,%s,%s,%s)",
               (tenant, f"{tenant}-{time.time_ns()}-{i}", "p", cols.get("work_secs", 0)))


def counts():
    return {r["status"]: r["n"] for r in db.run("SELECT status, count(*) AS n FROM jobs GROUP BY status")}


def wait(cond, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_never_more_than_max_inflight_and_rest_waits_in_postgres():
    d = start("app.dispatcher", MAX_INFLIGHT=5, DISPATCH_INTERVAL=0.1)      # NO worker: nothing finishes
    try:
        add_jobs("alice", 20)
        assert wait(lambda: counts().get("DISPATCHED") == 5)
        time.sleep(1)                                                       # give it time to (wrongly) send more
        assert counts() == {"DISPATCHED": 5, "QUEUED": 15}
        assert mq.publisher.depth(mq.WORK) == 5                             # the broker holds only 5
    finally:
        d.kill()


# pg_locks lists locks of EVERY database in the server, so only count the ones in this (test) database.
LEADERS = """SELECT a.pid FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
             WHERE l.locktype = 'advisory' AND l.objid = 4242 AND l.granted
             AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())"""


def test_only_one_of_two_dispatchers_leads():
    d1 = start("app.dispatcher", DISPATCH_INTERVAL=0.1)
    d2 = start("app.dispatcher", DISPATCH_INTERVAL=0.1)
    try:
        assert wait(lambda: len(db.run(LEADERS)) == 1)
        time.sleep(2)
        assert len(db.run(LEADERS)) == 1                                    # exactly one leader, never two
    finally:
        d1.kill(); d2.kill()


def test_standby_takes_over_within_seconds_when_leader_is_killed():
    d1 = start("app.dispatcher", DISPATCH_INTERVAL=0.1)
    assert wait(lambda: db.run(LEADERS))
    first = db.run(LEADERS)[0]["pid"]
    d2 = start("app.dispatcher", DISPATCH_INTERVAL=0.1)                     # starts as standby
    time.sleep(2)
    try:
        t0 = time.time()
        d1.kill()                                                           # leader dies (SIGKILL)
        assert wait(lambda: (h := db.run(LEADERS)) and h[0]["pid"] != first, 10)
        assert time.time() - t0 < 5
    finally:
        d1.kill(); d2.kill()


def test_reconciler_requeues_expired_lease_and_lost_dispatch_then_jobs_finish():
    # one job "RUNNING" whose worker died long ago, one "DISPATCHED" whose message was never published
    db.run("""INSERT INTO jobs (tenant, idem_key, prompt, status, attempts, lease_expires_at)
              VALUES ('alice','dead-worker','p','RUNNING',1, now() - interval '1 minute')""")
    db.run("""INSERT INTO jobs (tenant, idem_key, prompt, status, dispatched_at, dispatch_seq)
              VALUES ('alice','lost-msg','p','DISPATCHED', now() - interval '1 minute', 1)""")
    d = start("app.dispatcher", DISPATCH_INTERVAL=0.1, RECONCILE_EVERY=0.5, DISPATCH_TIMEOUT=5)
    w = start("app.worker")
    try:
        assert wait(lambda: counts().get("SUCCEEDED") == 1, 15)             # the expired-lease job is recovered
        assert wait(lambda: counts().get("SUCCEEDED") == 2, 20)             # the lost DISPATCHED job after DISPATCH_TIMEOUT
        assert all(r["attempts"] <= 2 for r in db.run("SELECT attempts FROM jobs"))
    finally:
        d.kill(); w.kill()


def test_interactive_beats_batch_for_the_provider_budget():
    b = SyncBudget("redis://localhost:6379/1")
    b.r.delete("rl:conc:provider")
    import app.provider_budget as pb
    pb.SLOTS, pb.BATCH_SHARE = 4, 0.5                                       # 4 slots; batch may use at most 2
    assert limit_for("batch") == 2 and limit_for("interactive") == 4
    batch = [b.acquire("batch", wait_seconds=0.3) for _ in range(4)]
    assert [s is not None for s in batch] == [True, True, False, False]     # batch is capped at 2 slots
    inter = [b.acquire("interactive", wait_seconds=0.3) for _ in range(3)]
    assert [s is not None for s in inter] == [True, True, False]            # interactive takes the other 2 (4 in total)
    b.r.delete("rl:conc:provider")
    pb.SLOTS, pb.BATCH_SHARE = 400, 0.5
