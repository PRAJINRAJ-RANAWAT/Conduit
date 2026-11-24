"""Stop RabbitMQ.
EXPECTED: POST /jobs still answers 202 (the job is saved in Postgres and stays QUEUED; only the dispatcher needs the broker).
          Chat is unaffected. The dispatcher and workers reconnect by themselves when RabbitMQ is back, and every job
          submitted before, during and after the outage ends SUCCEEDED (0 lost, 0 duplicates: attempts == 1), with NO client retries.
(First version of this test, before the dispatcher existed, expected a 503 and a client retry; see chaos/results/first_run/.)
"""
from lib import *

dc("up", "-d", "worker", "dispatcher")
ids = [submit(1)[1].json()["id"]]
wait_until(lambda: any(j["status"] == "SUCCEEDED" for j in jobs()), 20)
dc("stop", "rabbitmq"); say("rabbitmq stopped")
say("chat while rabbitmq is down: HTTP " + str(chat(f"q-{RUN}").status_code))
codes = []
for n in range(2, 7):                          # 5 jobs submitted during the outage
    r = submit(n)[1]; codes.append(r.status_code); ids.append(r.json()["id"])
say(f"job submits while rabbitmq is down: {codes}")
time.sleep(4)
say("job states while down: " + str(sorted({j['status'] for j in jobs() if j['id'] in ids[1:]})))
dc("start", "rabbitmq"); say("rabbitmq started; waiting for it to be healthy")
wait_until(lambda: "healthy" in dc("ps", "rabbitmq"), 60, every=2)
done = wait_until(lambda: all(j["status"] == "SUCCEEDED" for j in jobs() if j["id"] in ids), 90)
mine = [j for j in jobs() if j["id"] in ids]
say("final: " + str([(j["status"], j["attempts"]) for j in mine]))
verdict(all(c == 202 for c in codes) and done and len(mine) == 6 and all(j["attempts"] == 1 for j in mine),
        f"202_while_down={all(c == 202 for c in codes)}, all_finished_without_client_retry={done}, max_attempts={max(j['attempts'] for j in mine)}")
