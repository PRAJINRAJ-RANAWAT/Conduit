"""Call an LLM provider; if it fails, fall back to the next one.

Each provider has a CIRCUIT BREAKER, like a fuse:
  CLOSED    normal. Count failures in a row.
  OPEN      after 3 failures in a row: stop calling it for COOLDOWN seconds (fail fast).
  HALF-OPEN after the cooldown: let ONE probe call through. Success -> CLOSED, failure -> OPEN again.
State lives inside each gateway process (simple; each replica learns on its own).
"""
import os
import time
import httpx

COOLDOWN = float(os.getenv("BREAKER_COOLDOWN", "10"))
THRESHOLD = 3


class Breaker:
    def __init__(self):
        self.fails, self.opened_at, self.probing = 0, None, False

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.time() - self.opened_at >= COOLDOWN and not self.probing:
            self.probing = True            # half-open: exactly one probe at a time
            return True
        return False

    def success(self):
        self.fails, self.opened_at, self.probing = 0, None, False

    def failure(self):
        self.fails += 1
        self.probing = False
        if self.fails >= THRESHOLD:
            self.opened_at = time.time()   # (re)open

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half-open" if time.time() - self.opened_at >= COOLDOWN else "open"


def urls() -> dict:
    return {"A": os.getenv("PROVIDER_A_URL", "http://localhost:9000"),
            "B": os.getenv("PROVIDER_B_URL", "http://localhost:9001")}


breakers = {"A": Breaker(), "B": Breaker()}
client = httpx.AsyncClient(timeout=5)   # shared connection pool


class AllProvidersDown(Exception):
    pass


async def call(body: dict):
    """Returns (result_json, provider_name). Tries A, then B."""
    for name, url in urls().items():
        if not breakers[name].allow():
            continue
        try:
            resp = await client.post(f"{url}/v1/chat/completions", json=body)
            resp.raise_for_status()
            breakers[name].success()
            return resp.json(), name
        except httpx.HTTPError:
            breakers[name].failure()
    raise AllProvidersDown()
