"""RabbitMQ topology + a publisher with confirms.

  jobs (direct exchange) --work--> [jobs.work]  workers read from here
                         --dead--> [jobs.dlq]   jobs that failed too many times
  jobs.retry (direct)  --0/1/2--> [jobs.retry.N] no consumer! messages sit for DELAY ms (TTL),
                                  then are dead-lettered back into jobs.work. That is the
                                  delay queue: wait = TTL + dead-lettering, no plugin needed.

MQ_PREFIX / RETRY_DELAYS_MS let tests use their own short-delay copy of the topology.
"""
import json
import os
import threading

import pika

URL = os.getenv("RABBIT_URL", "amqp://guest:guest@localhost:5672/%2F")
P = os.getenv("MQ_PREFIX", "")
DELAYS_MS = [int(x) for x in os.getenv("RETRY_DELAYS_MS", "5000,30000,120000").split(",")]
EXCHANGE, RETRY_EXCHANGE = f"{P}jobs", f"{P}jobs.retry"
WORK, DLQ = f"{P}jobs.work", f"{P}jobs.dlq"
MAX_ATTEMPTS = 3  # 3rd failure -> DLQ. (So delays #1 and #2 are used; #3 only if you raise this.)


def declare(ch):
    ch.exchange_declare(EXCHANGE, "direct", durable=True)
    ch.exchange_declare(RETRY_EXCHANGE, "direct", durable=True)
    ch.queue_declare(WORK, durable=True)
    ch.queue_bind(WORK, EXCHANGE, "work")
    ch.queue_declare(DLQ, durable=True)
    ch.queue_bind(DLQ, EXCHANGE, "dead")
    for i, ms in enumerate(DELAYS_MS):
        q = f"{P}jobs.retry.{i}"
        ch.queue_declare(q, durable=True, arguments={
            "x-message-ttl": ms,                    # wait this long...
            "x-dead-letter-exchange": EXCHANGE,     # ...then move to the work queue
            "x-dead-letter-routing-key": "work"})
        ch.queue_bind(q, RETRY_EXCHANGE, str(i))


def connect():
    return pika.BlockingConnection(pika.URLParameters(URL))


class Publisher:
    """Thread-safe publisher. Every publish waits for the broker's confirm (it is on disk)."""

    def __init__(self):
        self.lock, self.conn, self.ch = threading.Lock(), None, None

    def _open(self):
        self.conn = connect()
        self.ch = self.conn.channel()
        self.ch.confirm_delivery()   # basic_publish now raises if the broker does not confirm
        declare(self.ch)

    def publish(self, exchange: str, key: str, body: dict):
        with self.lock:
            for attempt in (1, 2):   # one reconnect try if the connection died
                try:
                    if not self.ch or self.ch.is_closed:
                        self._open()
                    self.ch.basic_publish(
                        exchange, key, json.dumps(body), mandatory=True,
                        properties=pika.BasicProperties(delivery_mode=2))  # 2 = persistent
                    return
                except Exception:
                    self.ch = None
                    if attempt == 2:
                        raise

    def depth(self, queue: str) -> int:
        with self.lock:
            try:
                if not self.ch or self.ch.is_closed:
                    self._open()
                return self.ch.queue_declare(queue, passive=True).method.message_count
            except Exception:
                self.ch = None
                return -1   # broker unreachable


publisher = Publisher()
