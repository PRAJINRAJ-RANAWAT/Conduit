"""Integration tests use the REAL Redis, RabbitMQ and Postgres from docker compose.

They are kept apart from dev data: Redis db 1, a separate Postgres database, and a RabbitMQ
topology with prefix "test." and very short retry delays.
"""
import os
import psycopg

os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["MQ_PREFIX"] = "test."
os.environ["RETRY_DELAYS_MS"] = "300,600,1200"
os.environ["DATABASE_URL"] = "postgresql://conduit:conduit@localhost:5432/conduit_test"
os.environ["PROVIDER_A_URL"] = "http://localhost:9100"
os.environ["PROVIDER_B_URL"] = "http://localhost:9101"
os.environ["BREAKER_COOLDOWN"] = "1"

with psycopg.connect("postgresql://conduit:conduit@localhost:5432/conduit", autocommit=True) as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname='conduit_test'").fetchone():
        c.execute("CREATE DATABASE conduit_test")

import subprocess, sys, time
import pytest


@pytest.fixture(scope="session")
def mock_llm():
    """Two real mock-LLM processes: provider A on :9100, provider B on :9101."""
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.mock_provider:app",
                               "--port", str(port), "--log-level", "warning"]) for port in (9100, 9101)]
    time.sleep(1.5)
    yield
    for p in procs:
        p.kill()
