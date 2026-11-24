"""Dispatcher: moves QUEUED jobs from Postgres into RabbitMQ, fairly, and never too many at once.

 * Only ONE dispatcher is active (the "leader"): whoever holds a Postgres advisory lock. The others
   wait and take over when the leader's connection dies (the lock is released automatically).
 * It never lets more than MAX_INFLIGHT jobs be out in RabbitMQ / workers. The rest wait in Postgres,
   so the broker queue stays short and a tenant's new job never waits behind a huge backlog.
 * DISPATCH_MODE=fair picks jobs with Deficit Round Robin across tenants (weights in tenants.weight).
   DISPATCH_MODE=fifo picks the oldest job overall (only used as the "before" in the experiment).
 * A reconciler (leader only) repairs jobs whose worker or message was lost.
"""
import os
import socket
import time

import psycopg

from app import db, mq
from app.drr import DRR

MODE = os.getenv("DISPATCH_MODE", "fair")
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "50"))
INTERVAL = float(os.getenv("DISPATCH_INTERVAL", "0.2"))          # seconds between dispatch rounds
RECONCILE_EVERY = float(os.getenv("RECONCILE_EVERY", "5"))
DISPATCH_TIMEOUT = float(os.getenv("DISPATCH_TIMEOUT", "120"))   # a job may sit DISPATCHED this long
LOCK_KEY = 4242                                                  # the advisory lock = "I am the leader"
CLAIM = """UPDATE jobs SET status='DISPATCHED', dispatch_seq=dispatch_seq+1, dispatched_at=now(), updated_at=now()
           WHERE id IN (SELECT id FROM jobs WHERE status='QUEUED' {where}
                        ORDER BY priority DESC, created_at LIMIT %s FOR UPDATE SKIP LOCKED)
           RETURNING id::text, dispatch_seq"""
drr = DRR()


def claim(capacity: int) -> list[dict]:
    """Mark up to `capacity` jobs DISPATCHED (SKIP LOCKED: two dispatchers could never claim the same row)."""
    if MODE == "fifo":
        return db.run(CLAIM.format(where=""), (capacity,))
    queued = {r["tenant"]: r["n"] for r in db.run(
        "SELECT tenant, count(*) AS n FROM jobs WHERE status='QUEUED' GROUP BY tenant")}
    weights = {r["name"]: r["weight"] for r in db.run("SELECT name, weight FROM tenants")}
    claimed = []
    for tenant, n in drr.allocate(queued, weights, capacity).items():
        if n:
            claimed += db.run(CLAIM.format(where="AND tenant=%s"), (tenant, n))
    return claimed


def dispatch_once(pub) -> int:
    inflight = db.run("SELECT count(*) AS n FROM jobs WHERE status IN ('DISPATCHED','RUNNING','RETRYING')")[0]["n"]
    if inflight >= MAX_INFLIGHT:
        return 0                                        # backpressure: leave the work in Postgres
    jobs = claim(MAX_INFLIGHT - inflight)
    for i, job in enumerate(jobs):
        try:
            pub.publish(mq.EXCHANGE, "work", {"job_id": job["id"], "seq": job["dispatch_seq"]})
        except Exception:                               # RabbitMQ is down: put the unsent jobs back
            db.run("UPDATE jobs SET status='QUEUED', updated_at=now() WHERE id = ANY(%s::uuid[]) AND status='DISPATCHED'",
                   ([j["id"] for j in jobs[i:]],))
            raise
    return len(jobs)


def reconcile():
    """Repair jobs that were lost. Postgres is the source of truth; the broker is only transport."""
    # worker died and its message is gone: the lease ran out
    db.run("UPDATE jobs SET status='QUEUED', updated_at=now() WHERE status='RUNNING' AND lease_expires_at < now()")
    # we published but no worker ever picked it up (message lost): publish again. The new dispatch_seq makes
    # any old copy of the message harmless.
    db.run("UPDATE jobs SET status='QUEUED', updated_at=now() WHERE status='DISPATCHED' "
           "AND dispatched_at < now() - %s * interval '1 second'", (DISPATCH_TIMEOUT,))
    # waiting in a delay queue for much longer than the delay: that message is lost too
    db.run("UPDATE jobs SET status='QUEUED', updated_at=now() WHERE status='RETRYING' "
           "AND updated_at < now() - %s * interval '1 second'", (max(mq.DELAYS_MS) / 1000 + DISPATCH_TIMEOUT,))


def become_leader(host: str):
    """Block until we hold the advisory lock. Returns the connection that holds it (keep it open!)."""
    while True:
        try:
            conn = psycopg.connect(db.URL, autocommit=True, application_name=host)
            if conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
                return conn
            conn.close()
        except psycopg.Error:
            pass
        time.sleep(1)                                   # standby: try again in 1s


def lead(lock_conn, pub):
    """Run while we are leader. Any error ends leadership (the caller starts the election again)."""
    last_reconcile = 0.0
    while True:
        lock_conn.execute("SELECT 1")                   # fails if our lock connection died -> we are no longer leader
        dispatch_once(pub)
        if time.time() - last_reconcile > RECONCILE_EVERY:
            reconcile()
            last_reconcile = time.time()
        time.sleep(INTERVAL)


def main():
    db.init()
    pub, host = mq.Publisher(), socket.gethostname()
    while True:
        lock_conn = become_leader(host)
        print(f"dispatcher {host}: I am the leader (mode={MODE}, max_inflight={MAX_INFLIGHT})", flush=True)
        try:
            lead(lock_conn, pub)
        except Exception as e:
            print(f"dispatcher {host}: stopped leading ({type(e).__name__}); retrying", flush=True)
            time.sleep(2)
        finally:
            try:
                lock_conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
