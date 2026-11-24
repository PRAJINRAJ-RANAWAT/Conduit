"""API key -> tenant, looked up in Postgres (keys are stored hashed).

A small in-process cache keeps Postgres out of the hot path. Unknown keys are cached for a few
seconds, so someone guessing keys cannot hammer the database.

REVOCATION: when a key is revoked, the gateway that handled it PUBLISHES the key hash on a Redis
channel. Every gateway replica is subscribed and drops that key from its own cache at once (milliseconds).
The cache TTL below is only a safety net for a lost message (e.g. Redis was briefly down); if the
subscriber loses its connection it also clears the whole cache when it reconnects.
"""
import asyncio
import hashlib
import time

from fastapi import Header, HTTPException

from app import db

TTL_SECONDS = 60        # safety net only; revocation does not wait for this
NEGATIVE_TTL_SECONDS = 5
CHANNEL = "conduit:revoke"
_cache: dict = {}   # key_hash -> (expires_at, tenant dict or None)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def listen_for_revocations(r):
    """Background task, one per gateway replica: drop revoked keys from the local cache."""
    while True:
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(CHANNEL)
            _cache.clear()                    # we may have missed messages while disconnected
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    _cache.pop(msg["data"], None)
        except Exception:
            await asyncio.sleep(2)            # Redis is down: wait, then subscribe again


async def revoke(r, key: str):
    """Mark the key revoked in Postgres, then tell every replica (including this one)."""
    h = hash_key(key)
    await asyncio.to_thread(db.run, "UPDATE api_keys SET revoked=true WHERE key_hash=%s", (h,))
    _cache.pop(h, None)
    await r.publish(CHANNEL, h)


def create_tenant(name: str, tpm: int, conc: int, key: str):
    db.run("INSERT INTO tenants (name, tpm, conc) VALUES (%s,%s,%s) "
           "ON CONFLICT (name) DO UPDATE SET tpm=%s, conc=%s", (name, tpm, conc, tpm, conc))
    db.run("INSERT INTO api_keys (key_hash, tenant, prefix) VALUES (%s,%s,%s) "
           "ON CONFLICT (key_hash) DO UPDATE SET revoked=false", (hash_key(key), name, key[:8]))
    _cache.clear()


def seed():
    """Demo tenants for the playground and tests."""
    create_tenant("alice", 60_000, 20, "key-alice")
    create_tenant("bob", 300, 2, "key-bob")
    create_tenant("loadtest", 1_000_000_000, 5000, "key-load")   # huge quota: for benchmarks


def get_tenant(authorization: str = Header(default="")) -> dict:
    h = hash_key(authorization.removeprefix("Bearer "))
    hit = _cache.get(h)
    if hit and hit[0] > time.time():
        tenant = hit[1]
    else:
        rows = db.run("""SELECT t.name, t.tpm, t.conc FROM api_keys k
                         JOIN tenants t ON t.name = k.tenant
                         WHERE k.key_hash=%s AND NOT k.revoked""", (h,))
        tenant = rows[0] if rows else None
        ttl = TTL_SECONDS if tenant else NEGATIVE_TTL_SECONDS
        _cache[h] = (time.time() + ttl, tenant)
    if not tenant:
        raise HTTPException(401, "bad api key")
    return tenant
