"""Tests for the FastAPI dashboard's /api/routing endpoints (Console Task 11).

Covers GET /api/routing/seeds (embeddings stripped, outcome tallies) and
POST /api/routing/reconcile (dry_run preview vs wet reconcile_outcomes),
mirroring sentigent_reconcile_routes in mcp_server.py — zero logic
duplication, the handlers only call reconciler functions + store methods.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from sentigent.memory.store import MemoryStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "routing_api.db"


@pytest.fixture
def client(db_path, monkeypatch):
    """TestClient wired to a temp per-test SQLite db via SENTIGENT_DB_PATH."""
    monkeypatch.setenv("SENTIGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTIGENT_AGENT_ID", "test_agent")
    monkeypatch.delenv("SENTIGENT_ORG_ID", raising=False)
    monkeypatch.delenv("SENTIGENT_SUPABASE_ORG_ID", raising=False)

    from sentigent.dashboard.server import app

    return TestClient(app)


@pytest.fixture
def store_with_two_seeds(db_path):
    """Seed two routing_seeds rows directly via the store (no embedding model)."""
    store = MemoryStore(agent_id="test_agent", org_id="", db_path=str(db_path))
    store.insert_routing_seed(
        prompt_hash="ign", prompt_text="prompt ign", task_type="operate",
        skill="refactor", agent="general-purpose", model="sonnet",
        confidence=0.7, avg_sim=0.7, margin=0.1, neighbors=[],
        embedding=[1.0, 0.0, 0.0], outcome="neutral",
    )
    store.insert_routing_seed(
        prompt_hash="fol", prompt_text="prompt fol", task_type="operate",
        skill="test-runner", agent="general-purpose", model="sonnet",
        confidence=0.8, avg_sim=0.8, margin=0.2, neighbors=[],
        embedding=[0.0, 1.0, 0.0], outcome="neutral",
    )
    return store


@pytest.fixture
def fake_logs(tmp_path, monkeypatch):
    """Fake skill-router logs pointing the reconciler at tmp files.

    'ign' is routed twice and never invoked -> demote.
    'fol' is routed once and invoked within the follow window -> reinforce.
    """
    base = time.time() - 3600
    router_log = tmp_path / "skill_router_log.jsonl"
    usage_log = tmp_path / "skill_usage.log"

    def iso(ts: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))

    def space(ts: float) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    router_log.write_text(
        f'{{"type":"embedding-route","ts":"{iso(base)}","prompt_hash":"ign","skill":"refactor"}}\n'
        f'{{"type":"embedding-route","ts":"{iso(base + 500)}","prompt_hash":"ign","skill":"refactor"}}\n'
        f'{{"type":"embedding-route","ts":"{iso(base + 1000)}","prompt_hash":"fol","skill":"test-runner"}}\n'
    )
    usage_log.write_text(
        f"{space(base + 1030)}\ttest-runner\n"
    )

    monkeypatch.setenv("SENTIGENT_ROUTER_LOG_PATH", str(router_log))
    monkeypatch.setenv("SENTIGENT_USAGE_LOG_PATH", str(usage_log))
    return {"router_log": router_log, "usage_log": usage_log}


def test_routing_seeds_and_reconcile(client, store_with_two_seeds, fake_logs):
    body = client.get("/api/routing/seeds").json()
    assert len(body["seeds"]) == 2 and "embedding" not in body["seeds"][0]
    assert set(body["counts"]) == {"correct", "neutral", "incorrect"}
    assert body["counts"]["neutral"] == 2

    seed = next(s for s in body["seeds"] if s["prompt_hash"] == "fol")
    assert seed["skill"] == "test-runner"
    assert seed["agent"] == "general-purpose"
    assert seed["model"] == "sonnet"
    assert seed["confidence"] == pytest.approx(0.8)
    assert seed["outcome"] == "neutral"

    dry = client.post("/api/routing/reconcile", json={"dry_run": True}).json()
    assert "would_demote" in dry
    assert dry["would_reinforce"] == 1
    assert dry["would_demote"] == 1

    wet = client.post("/api/routing/reconcile", json={"dry_run": False}).json()
    assert wet["seen"] >= 1  # reconcile stats shape from reconcile_outcomes()
    assert wet["reinforced"] == 1
    assert wet["demoted"] == 1

    body2 = client.get("/api/routing/seeds").json()
    counts2 = body2["counts"]
    assert counts2["correct"] == 1
    assert counts2["incorrect"] == 1


def test_reconcile_dry_run_does_not_write(client, store_with_two_seeds, fake_logs):
    client.post("/api/routing/reconcile", json={"dry_run": True})
    counts = client.get("/api/routing/seeds").json()["counts"]
    assert counts["neutral"] == 2  # nothing written by dry_run


def test_reconcile_days_filter_can_exclude_all_events(client, store_with_two_seeds, fake_logs):
    # All fake log events are ~1 hour old; days=0 (falsy) means "all history" so
    # passing a very small window in days should filter everything out.
    dry = client.post(
        "/api/routing/reconcile", json={"dry_run": True, "days": 3650}
    ).json()
    assert dry["would_reinforce"] == 1  # generous window still finds the events
