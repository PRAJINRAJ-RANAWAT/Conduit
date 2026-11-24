"""Small helpers shared by the chaos scripts. Needs the compose stack running (docker compose up -d)."""
import subprocess
import sys
import time
import uuid
import httpx

G = "http://localhost:8080"
H = {"Authorization": "Bearer key-alice"}
RUN = uuid.uuid4().hex[:6]


def dc(*args):
    """Run a `docker compose` command, e.g. dc("stop", "redis")."""
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True).stdout


def submit(n: int, **extra):
    """Submit one job; retries with the SAME key if the API says 503 (that is what a client should do)."""
    key = f"{RUN}-{n}"
    r = httpx.post(f"{G}/jobs", headers={**H, "Idempotency-Key": key},
                   json={"prompt": f"chaos {n}", **extra}, timeout=10)
    return key, r


def jobs():
    return httpx.get(f"{G}/jobs", headers=H, timeout=10).json()


def wait_until(check, seconds, every=1):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(every)
    return False


def chat(text: str):
    return httpx.post(f"{G}/v1/chat/completions", headers=H, timeout=10,
                      json={"max_tokens": 5, "messages": [{"role": "user", "content": text}]})


def say(msg):
    print(msg, flush=True)


def verdict(ok: bool, detail: str):
    say(f"RESULT: {'PASS' if ok else 'FAIL'}  {detail}")
    sys.exit(0 if ok else 1)
