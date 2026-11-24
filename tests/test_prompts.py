"""Prompt tests: real Postgres + mock LLM (eval mode)."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db, main, optimiser

H = {"Authorization": "Bearer key-alice"}


@pytest.fixture(scope="module")
def client(mock_llm):
    with TestClient(main.app) as c:
        yield c


def test_versions_cannot_be_updated_or_deleted(client):
    with pytest.raises(psycopg.errors.RaiseException):
        db.run("UPDATE prompt_versions SET template='hacked' WHERE version=1")
    with pytest.raises(psycopg.errors.RaiseException):
        db.run("DELETE FROM prompt_versions")


def test_new_version_gets_next_number(client):
    before = len(client.get("/prompts/tmp/versions", headers=H).json())
    r = client.post("/prompts/tmp/versions", json={"template": "x {text}"}, headers=H)
    assert r.json()["version"] == before + 1


def test_golden_set_has_20_examples():
    assert len(optimiser.GOLDEN) == 20


def test_optimiser_is_deterministic_and_saves_cost(client):
    a = client.post("/prompts/optimise", json={"epsilon": 0.1}, headers=H).json()
    b = client.post("/prompts/optimise", json={"epsilon": 0.1}, headers=H).json()
    assert a == b                                              # same input, same report
    assert a["best"]["score"] >= a["baseline"]["score"] - 0.1  # quality within epsilon
    assert a["best"]["avg_input_tokens"] < a["baseline"]["avg_input_tokens"]
    assert a["cost_saved_pct"] > 0


def test_tight_epsilon_keeps_baseline(client):
    r = client.post("/prompts/optimise", json={"epsilon": 0.0}, headers=H).json()
    assert r["best"]["score"] >= r["baseline"]["score"]
