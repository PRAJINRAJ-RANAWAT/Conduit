"""Kill -9 the worker in the middle of jobs.
EXPECTED: the dead worker's unacked message goes back to the queue; a new worker takes it over.
          All 5 jobs end SUCCEEDED (0 lost), none run twice to completion; the killed job shows attempts >= 2.
"""
from lib import *

say("starting from a clean worker"); dc("up", "-d", "worker")
ids = [submit(i, work_secs=4)[1].json()["id"] for i in range(5)]
wait_until(lambda: any(j["status"] == "RUNNING" for j in jobs()), 10)
say("a job is RUNNING -> kill -9 the worker now"); dc("kill", "-s", "SIGKILL", "worker")
time.sleep(2)
say("states right after the kill: " + str(sorted(j["status"] for j in jobs() if j["id"] in ids)))
say("starting a fresh worker"); dc("up", "-d", "worker")
done = wait_until(lambda: all(j["status"] == "SUCCEEDED" for j in jobs() if j["id"] in ids), 60)
mine = [j for j in jobs() if j["id"] in ids]
say("final: " + str([(j["status"], j["attempts"]) for j in mine]))
lost = sum(j["status"] != "SUCCEEDED" for j in mine)
verdict(done and len(mine) == 5 and lost == 0 and max(j["attempts"] for j in mine) >= 2,
        f"{len(mine)} jobs, lost={lost}, retaken after crash={sum(j['attempts'] >= 2 for j in mine)}")
