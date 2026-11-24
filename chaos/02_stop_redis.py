"""Stop Redis (limiter + cache live there).
EXPECTED: chat calls fail FAST with a clean HTTP 503 + Retry-After (not a hang, not a crash). Jobs still work (they use Postgres + RabbitMQ only).
          When Redis comes back, chat works again with no restart of the gateway.
"""
from lib import *

say("baseline chat: " + str(chat(f"r-{RUN}-0").status_code))
dc("stop", "redis"); say("redis stopped")
t = time.time()
try:
    r = chat(f"r-{RUN}-1"); chat_down = f"HTTP {r.status_code}"
except Exception as e:
    chat_down = f"exception {type(e).__name__}"
secs = time.time() - t
say(f"chat while redis is down: {chat_down} after {secs:.2f}s")
key, r = submit(1); job_ok = r.status_code in (200, 202)
say(f"job submit while redis is down: HTTP {r.status_code}")
dc("start", "redis"); say("redis started")
back = wait_until(lambda: chat(f"r-{RUN}-2").status_code == 200, 30, every=2)
say(f"chat works again: {back}")
verdict(secs < 5 and chat_down == "HTTP 503" and job_ok and back,
        f"chat_down={chat_down}, fast={secs < 5}, jobs_ok={job_ok}, recovered={back}")
