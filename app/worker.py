"""Worker: takes a job message, runs it, saves the result, THEN acks.

Why this is safe:
 - Ack comes last. If we crash before it, RabbitMQ redelivers the message.
 - Claiming is a conditional UPDATE, so a duplicate message can never run the job twice. Every message
   carries the job's dispatch_seq; if the dispatcher re-dispatched the job since, old messages no longer match.
 - A RUNNING job has a lease that a heartbeat thread keeps extending. If we die, the lease runs out and the
   dispatcher's reconciler gives the job back to the queue.
 - Failures go to a delay queue; after MAX_ATTEMPTS the job is marked DEAD and sent to the DLQ.
 - Provider calls take a slot from the shared provider budget (batch jobs get only the residual share).
"""
import json
import os
import threading
import time

import httpx

from app import db, mq
from app.provider_budget import SyncBudget

# Try provider A, then B (the gateway has a circuit breaker; the worker just falls back).
PROVIDER_URLS = [os.getenv("PROVIDER_A_URL", "http://localhost:9000"),
                 os.getenv("PROVIDER_B_URL", "http://localhost:9001")]
LEASE = float(os.getenv("LEASE_SECONDS", "30"))
budget = SyncBudget(os.getenv("REDIS_URL", "redis://localhost:6379"))


def claim(job_id: str, seq: int, redelivered: bool):
    """Move the job to RUNNING and count the attempt. Returns the row, or None for a stale/duplicate message."""
    # redelivered=True means a worker died holding this message, so a RUNNING job is ours to retake.
    states = ["DISPATCHED", "RETRYING", "QUEUED"] + (["RUNNING"] if redelivered else [])
    rows = db.run("""UPDATE jobs SET status='RUNNING', attempts=attempts+1, started_at=COALESCE(started_at, now()),
                     lease_expires_at=now() + %s * interval '1 second', updated_at=now()
                     WHERE id=%s AND dispatch_seq=%s AND status = ANY(%s) RETURNING *""",
                  (LEASE, job_id, seq, states))
    return rows[0] if rows else None


def heartbeat(job_id: str, stop: threading.Event):
    """While the job runs, keep pushing its lease forward."""
    while not stop.wait(LEASE / 3):
        db.run("UPDATE jobs SET lease_expires_at=now() + %s * interval '1 second' WHERE id=%s AND status='RUNNING'",
               (LEASE, job_id))


def do_work(job) -> dict:
    if job["attempts"] <= job["fail_times"]:      # demo switch: simulate a failing job
        raise RuntimeError(f"simulated failure on attempt {job['attempts']}")
    time.sleep(job["work_secs"])                  # demo switch: pretend the job is slow
    klass = "interactive" if job["priority"] > 0 else "batch"
    slot = budget.acquire(klass)
    if slot is None:
        raise RuntimeError("provider budget busy")
    try:
        body = {"messages": [{"role": "user", "content": job["prompt"]}], "max_tokens": 20}
        for url in PROVIDER_URLS:
            try:
                resp = httpx.post(f"{url}/v1/chat/completions", json=body, timeout=10)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError:
                continue
        raise RuntimeError("all providers failed")
    finally:
        budget.release(slot)


def handle(pub, ch, method, props, body):
    msg = json.loads(body)
    job = claim(msg["job_id"], msg["seq"], method.redelivered)
    if job is None:                                # duplicate or stale: drop it
        return ch.basic_ack(method.delivery_tag)
    job_id, stop = msg["job_id"], threading.Event()
    threading.Thread(target=heartbeat, args=(job_id, stop), daemon=True).start()
    try:
        result = do_work(job)
        db.run("UPDATE jobs SET status='SUCCEEDED', result=%s, finished_at=now(), updated_at=now() WHERE id=%s",
               (json.dumps(result), job_id))       # 1. save the result...
    except Exception as e:
        if job["attempts"] >= mq.MAX_ATTEMPTS:
            db.run("UPDATE jobs SET status='DEAD', error=%s, finished_at=now(), updated_at=now() WHERE id=%s",
                   (str(e), job_id))
            pub.publish(mq.EXCHANGE, "dead", {"job_id": job_id, "seq": msg["seq"]})
        else:
            db.run("UPDATE jobs SET status='RETRYING', error=%s, updated_at=now() WHERE id=%s", (str(e), job_id))
            delay_queue = min(job["attempts"] - 1, len(mq.DELAYS_MS) - 1)
            pub.publish(mq.RETRY_EXCHANGE, str(delay_queue), {"job_id": job_id, "seq": msg["seq"]})
    finally:
        stop.set()
    ch.basic_ack(method.delivery_tag)              # 2. ...and only now ack


def consume(pub):
    conn = mq.connect()
    ch = conn.channel()
    mq.declare(ch)
    ch.basic_qos(prefetch_count=1)                 # one job at a time per worker
    ch.basic_consume(mq.WORK, lambda c, m, p, b: handle(pub, c, m, p, b))
    print("worker ready", flush=True)
    ch.start_consuming()


def main():
    db.init()
    pub = mq.Publisher()
    while True:                                    # if RabbitMQ (or anything) drops, wait and reconnect
        try:
            consume(pub)
        except Exception as e:
            print(f"worker lost its connection ({type(e).__name__}); retrying in 3s", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
