"""API key -> tenant, looked up in Postgres (keys are stored hashed).

A small in-process cache (30s) keeps Postgres out of the hot path. Unknown keys are cached too,
so someone guessing keys cannot hammer the database. Trade-off: revoking a key can take up to 30s
to be noticed by a gateway that has the key cached.
"""
import hashlib
import time
from fastapi import Header, HTTPException
from app import db

TTL_SECONDS = 30
_cache: dict = {}   # key_hash -> (expires_at, tenant dict or None)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


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
        _cache[h] = (time.time() + TTL_SECONDS, tenant)
    if not tenant:
        raise HTTPException(401, "bad api key")
    return tenant
