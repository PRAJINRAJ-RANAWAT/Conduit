"""Queue tests: real RabbitMQ + Postgres + a real worker process + a real mock-LLM process."""
import json
import os
import subprocess
import sys
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from app import db, main, mq

H = {"Authorization": "Bearer key-alice"}


@pytest.fixture(scope="module")
def stack():
    """Start mock LLM (:9100) and one worker; give each test a clean queue + table."""
    env = dict(os.environ)
    mock = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.mock_provider:app",
                             "--port", "9100", "--log-level", "warning"], env=env)
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"], env=env)
    with TestClient(main.app) as client:        # runs startup -> opens the DB pool
        time.sleep(2)
        yield client
    worker.kill(); mock.kill()


@pytest.fixture(autouse=True)
def clean(stack):
    db.run("TRUNCATE jobs")
    ch = mq.connect().channel()
    for q in [mq.WORK, mq.DLQ] + [f"{mq.P}jobs.retry.{i}" for i in range(3)]:
        ch.queue_purge(q)
    yield


def submit(client, prompt="hello", key=None, **extra):
    return client.post("/jobs", json={"prompt": prompt, **extra},
                       headers={**H, "Idempotency-Key": key or uuid.uuid4().hex})


def wait_for(client, job_id, status, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/jobs/{job_id}", headers=H).json()
        if job["status"] == status:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job stuck in {job['status']}")


def test_job_succeeds(stack):
    jid = submit(stack).json()["id"]
    job = wait_for(stack, jid, "SUCCEEDED")
    assert job["attempts"] == 1 and job["result"]["choices"]


def test_same_idempotency_key_gives_same_job(stack):
    a = submit(stack, key="k1")
    b = submit(stack, key="k1")
    assert a.status_code == 202 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert db.run("SELECT count(*) AS n FROM jobs")[0]["n"] == 1


def test_missing_idempotency_key_rejected(stack):
    assert stack.post("/jobs", json={"prompt": "x"}, headers=H).status_code == 400


def test_failing_job_retries_then_succeeds(stack):
    jid = submit(stack, fail_times=1).json()["id"]
    assert wait_for(stack, jid, "SUCCEEDED")["attempts"] == 2


def test_always_failing_job_goes_dead_after_3_attempts_and_into_dlq(stack):
    jid = submit(stack, fail_times=99).json()["id"]
    assert wait_for(stack, jid, "DEAD")["attempts"] == 3
    time.sleep(0.5)
    assert mq.publisher.depth(mq.DLQ) == 1


def test_duplicate_message_does_not_run_job_twice(stack):
    jid = submit(stack).json()["id"]
    wait_for(stack, jid, "SUCCEEDED")
    for _ in range(3):                                   # inject duplicate deliveries
        mq.publisher.publish(mq.EXCHANGE, "work", {"job_id": jid})
    time.sleep(1.5)
    assert stack.get(f"/jobs/{jid}", headers=H).json()["attempts"] == 1


def test_other_tenant_cannot_read_job(stack):
    jid = submit(stack).json()["id"]
    r = stack.get(f"/jobs/{jid}", headers={"Authorization": "Bearer key-bob"})
    assert r.status_code == 404
