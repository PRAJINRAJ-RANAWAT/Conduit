"""Tests run against REAL Redis (db 1, so dev data in db 0 is untouched)."""
import os
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
