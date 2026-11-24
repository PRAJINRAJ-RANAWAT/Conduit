"""One budget of concurrent provider calls, shared by everyone, with PRIORITY.

There are SLOTS provider calls allowed at the same moment. Interactive traffic (chat requests) may use
every slot. Batch traffic (background jobs) may only take a slot while fewer than SLOTS * BATCH_SHARE
are in use, so the rest is always kept free for interactive callers. When interactive traffic is heavy,
batch simply waits: interactive wins.  (A slot expires on its own after 60s, so a crash cannot leak it.)
"""
import os
import time
import uuid

import redis

from app.limiter import ACQUIRE

SLOTS = int(os.getenv("PROVIDER_SLOTS", "400"))
BATCH_SHARE = float(os.getenv("BATCH_SHARE", "0.5"))
KEY = "rl:conc:provider"        # same zset layout the limiter's concurrency scripts use


def limit_for(klass: str) -> int:
    return SLOTS if klass == "interactive" else max(1, int(SLOTS * BATCH_SHARE))


class SyncBudget:
    """Used by the (blocking) worker. The gateway uses Limiter.acquire_slot("provider", limit_for(...))."""

    def __init__(self, url: str):
        self.r = redis.Redis.from_url(url)
        self.acquire_lua = self.r.register_script(ACQUIRE)

    def acquire(self, klass: str, wait_seconds: float = 30):
        """Wait (up to wait_seconds) for a slot. Returns the slot id or None."""
        slot, end = uuid.uuid4().hex, time.time() + wait_seconds
        while time.time() < end:
            if self.acquire_lua(keys=[KEY], args=[limit_for(klass), slot, 60_000]):
                return slot
            time.sleep(0.1)
        return None

    def release(self, slot: str):
        self.r.zrem(KEY, slot)
