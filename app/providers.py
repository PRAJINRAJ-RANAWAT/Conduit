"""Call an LLM provider; if it fails, fall back to the next one.

Each provider has a CIRCUIT BREAKER, like a fuse:
  CLOSED    normal. Count failures in a row.
  OPEN      after 3 failures in a row: stop calling it for COOLDOWN seconds (fail fast).
  HALF-OPEN after the cooldown: let ONE probe call through. Success -> CLOSED, failure -> OPEN again.

The state lives in REDIS, so every gateway replica agrees: if replica 1 sees A failing, replica 2
stops calling A too. Keys (per provider NAME):
  cb:NAME:fails    failures in a row (expires after 60s without a new failure)
  cb:NAME:tripped  exists = the breaker has tripped and is not yet proven healthy again
  cb:NAME:open     exists = still inside the cooldown (expires by itself = cooldown over)
  cb:NAME:probe    exists = one replica is already running the half-open probe (SET NX = only one wins)
"""
import os

import httpx

COOLDOWN = float(os.getenv("BREAKER_COOLDOWN", "10"))
THRESHOLD = 3


class Breaker:
    def __init__(self, r, name: str):
        self.r, self.k = r, lambda part: f"cb:{name}:{part}"

    async def allow(self) -> bool:
        if not await self.r.exists(self.k("tripped")):
            return True                                   # closed
        if await self.r.exists(self.k("open")):
            return False                                  # open: inside the cooldown
        # half-open: exactly one probe at a time, across ALL replicas
        return bool(await self.r.set(self.k("probe"), 1, nx=True, px=5000))

    async def success(self):
        await self.r.delete(*[self.k(p) for p in ("fails", "tripped", "open", "probe")])

    async def failure(self):
        fails = await self.r.incr(self.k("fails"))
        await self.r.expire(self.k("fails"), 60)
        await self.r.delete(self.k("probe"))
        # trip after THRESHOLD failures in a row, or re-open at once if a half-open probe failed
        if fails >= THRESHOLD or await self.r.exists(self.k("tripped")):
            await self.r.set(self.k("tripped"), 1)
            await self.r.set(self.k("open"), 1, px=int(COOLDOWN * 1000))

    async def state(self) -> str:
        if not await self.r.exists(self.k("tripped")):
            return "closed"
        return "open" if await self.r.exists(self.k("open")) else "half-open"


def urls() -> dict:
    return {"A": os.getenv("PROVIDER_A_URL", "http://localhost:9000"),
            "B": os.getenv("PROVIDER_B_URL", "http://localhost:9001")}


client = httpx.AsyncClient(timeout=5)   # shared connection pool


class AllProvidersDown(Exception):
    pass


async def states(r) -> dict:
    return {name: await Breaker(r, name).state() for name in urls()}


async def call(body: dict, r):
    """Returns (result_json, provider_name). Tries A, then B."""
    for name, url in urls().items():
        breaker = Breaker(r, name)
        if not await breaker.allow():
            continue
        try:
            resp = await client.post(f"{url}/v1/chat/completions", json=body)
            resp.raise_for_status()
            await breaker.success()
            return resp.json(), name
        except httpx.HTTPError:
            await breaker.failure()
    raise AllProvidersDown()
