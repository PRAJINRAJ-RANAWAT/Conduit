"""API key -> tenant. (Step 4 swaps the dict for a Postgres lookup.)"""
from fastapi import Header, HTTPException

TENANTS = {
    "key-alice": {"name": "alice", "tpm": 60_000, "conc": 20},
    "key-bob": {"name": "bob", "tpm": 300, "conc": 2},
}


def get_tenant(authorization: str = Header(default="")) -> dict:
    tenant = TENANTS.get(authorization.removeprefix("Bearer "))
    if not tenant:
        raise HTTPException(401, "bad api key")
    return tenant
