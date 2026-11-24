"""Worker: takes a job message, runs it, saves the result, THEN acks.

Why this is safe:
 - Ack comes last. If we crash before it, RabbitMQ redelivers the message.
 - Claiming is a conditional UPDATE, so a duplicate message can never run the job twice.
 - Failures go to a delay queue; after MAX_ATTEMPTS the job is marked DEAD and sent to the DLQ.
"""
import json
import os
import httpx
from app import db, mq

PROVIDER_URL = os.getenv("PROVIDER_URL", "http://localhost:9000")


def claim(job_id: str, redelivered: bool):
    """Move the job to RUNNING and count the attempt. Returns the row, or None for a duplicate."""
    states = "('QUEUED','RETRYING','RUNNING')" if redelivered else "('QUEUED','RETRYING')"
    # redelivered=True means a worker died holding this message, so a RUNNING job is ours to retake.
    rows = db.run(f"""UPDATE jobs SET status='RUNNING', attempts=attempts+1
                      WHERE id=%s AND status IN {states} RETURNING *""", (job_id,))
    return rows[0] if rows else None


def do_work(job) -> dict:
    if job["attempts"] <= job["fail_times"]:      # demo switch: simulate a failing job
        raise RuntimeError(f"simulated failure on attempt {job['attempts']}")
    body = {"messages": [{"role": "user", "content": job["prompt"]}], "max_tokens": 20}
    resp = httpx.post(f"{PROVIDER_URL}/v1/chat/completions", json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def handle(pub, ch, method, props, body):
    job_id = json.loads(body)["job_id"]
    job = claim(job_id, method.redelivered)
    if job is None:                                # duplicate or already finished: drop it
        return ch.basic_ack(method.delivery_tag)
    try:
        result = do_work(job)
        db.run("UPDATE jobs SET status='SUCCEEDED', result=%s WHERE id=%s",
               (json.dumps(result), job_id))       # 1. save the result...
    except Exception as e:
        if job["attempts"] >= mq.MAX_ATTEMPTS:
            db.run("UPDATE jobs SET status='DEAD', error=%s WHERE id=%s", (str(e), job_id))
            pub.publish(mq.EXCHANGE, "dead", {"job_id": job_id})
        else:
            db.run("UPDATE jobs SET status='RETRYING', error=%s WHERE id=%s", (str(e), job_id))
            delay_queue = min(job["attempts"] - 1, len(mq.DELAYS_MS) - 1)
            pub.publish(mq.RETRY_EXCHANGE, str(delay_queue), {"job_id": job_id})
    ch.basic_ack(method.delivery_tag)              # 2. ...and only now ack


def main():
    db.init()
    pub = mq.Publisher()
    conn = mq.connect()
    ch = conn.channel()
    mq.declare(ch)
    ch.basic_qos(prefetch_count=1)                 # one job at a time per worker
    ch.basic_consume(mq.WORK, lambda c, m, p, b: handle(pub, c, m, p, b))
    print("worker ready", flush=True)
    ch.start_consuming()


if __name__ == "__main__":
    main()
