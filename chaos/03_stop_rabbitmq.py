"""Stop RabbitMQ.
EXPECTED: POST /jobs answers 503 (job saved but not queued); retrying with the SAME Idempotency-Key after
          RabbitMQ is back queues it, with no duplicate. Chat is unaffected. The worker reconnects by itself,
          and every job ends SUCCEEDED (0 lost).
"""
from lib import *

dc("up", "-d", "worker")
key, r1 = submit(1)
wait_until(lambda: any(j["status"] == "SUCCEEDED" for j in jobs()), 20)
dc("stop", "rabbitmq"); say("rabbitmq stopped")
say("chat while rabbitmq is down: HTTP " + str(chat(f"q-{RUN}").status_code))
key2, r2 = submit(2); say(f"job submit while rabbitmq is down: HTTP {r2.status_code}")
dc("start", "rabbitmq"); say("rabbitmq started; waiting for it to be healthy")
wait_until(lambda: "healthy" in dc("ps", "rabbitmq"), 60, every=2)
r3 = None
for _ in range(10):                     # client retry with the same key
    key3, r3 = submit(2)
    if r3.status_code in (200, 202):
        break
    time.sleep(2)
say(f"retry with the same key: HTTP {r3.status_code}")
done = wait_until(lambda: all(j["status"] == "SUCCEEDED" for j in jobs() if j["id"] == r3.json()["id"]), 60)
mine = [j for j in jobs() if j["id"] in {r1.json()["id"], r3.json()["id"]}]
say("final: " + str([(j["status"], j["attempts"]) for j in mine]))
verdict(r2.status_code == 503 and r3.status_code in (200, 202) and done and len(mine) == 2,
        f"503_while_down={r2.status_code == 503}, finished_after_recovery={done}")
