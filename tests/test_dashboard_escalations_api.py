"""Tests for the FastAPI dashboard's /api/escalations endpoints (Console Task 10).

Seeding mirrors tests/test_loop_calibration.py: monkeypatch loop_driver.LOOP_DIR to a
temp dir and loop_driver._open_store to a temp MemoryStore, then drive a loop into the
exact `blocked` + `open_escalation_*` shape step_once() produces when a real blocker
pages a human. The dashboard handlers must read/answer through the SAME loop_driver
functions (list_pending_escalations / answer) — no separate logic.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="dashboard extra not installed")
from fastapi.testclient import TestClient

from sentigent.memory.store import MemoryStore
from sentigent.operator import loop_driver as L


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient wired to a temp per-test loop dir + memory store."""
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    store = MemoryStore(agent_id="t", org_id="t", db_path=str(tmp_path / "brain.db"))
    monkeypatch.setattr(L, "_open_store", lambda: store)

    from sentigent.dashboard.server import app

    return TestClient(app)


@pytest.fixture
def seeded_escalation(client, tmp_path):
    """A loop blocked on step 0 with an open escalation waiting on a human answer."""
    state = L.start("ship the thing", ["deploy the service"], cwd=str(tmp_path))
    step = state["steps"][0]
    step["status"] = "failed"
    step["last_error"] = "prod deploy needs a human sign-off"
    step["ended_at"] = 111.0
    state["status"] = "blocked"
    eid = L._persist_escalation(
        state, step, {"decision": "approve", "confidence": 0.8, "category": "deploy"}
    )
    state["open_escalation_id"] = eid
    state["open_escalation_step"] = step["i"]
    L._save(state)
    return {"loop_id": state["loop_id"], "step": step["i"]}


class TestEscalationsList:
    def test_list_empty(self, client):
        r = client.get("/api/escalations")
        assert r.status_code == 200
        assert r.json() == {"pending": []}

    def test_list_shows_seeded_escalation(self, client, seeded_escalation):
        r = client.get("/api/escalations")
        assert r.status_code == 200
        pending = r.json()["pending"]
        assert len(pending) == 1
        item = pending[0]
        assert item["loop_id"] == seeded_escalation["loop_id"]
        assert item["step"] == seeded_escalation["step"]
        assert item["title"] == "deploy the service"
        assert item["blocker"] == "prod deploy needs a human sign-off"
        assert item["asked_at"] == 111.0

    def test_running_loop_is_not_pending(self, client, tmp_path):
        L.start("ship it", ["write the code"], cwd=str(tmp_path))
        r = client.get("/api/escalations")
        assert r.json() == {"pending": []}


class TestEscalationsAnswer:
    def test_answer_skip_returns_200_and_delegates_to_loop_driver(self, client, seeded_escalation):
        r = client.post(
            f"/api/escalations/{seeded_escalation['loop_id']}/answer",
            json={"decision": "skip"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["loop_id"] == seeded_escalation["loop_id"]
        assert body["answer"] == "skip"
        assert body["status"] == "running"

        reloaded = L.load(seeded_escalation["loop_id"])
        assert reloaded["steps"][0]["status"] == "pending"
        assert "open_escalation_id" not in reloaded

    def test_answer_clears_it_from_pending_list(self, client, seeded_escalation):
        client.post(
            f"/api/escalations/{seeded_escalation['loop_id']}/answer",
            json={"decision": "approve"},
        )
        assert client.get("/api/escalations").json()["pending"] == []

    def test_answer_unknown_decision_is_400(self, client, seeded_escalation):
        r = client.post(
            f"/api/escalations/{seeded_escalation['loop_id']}/answer",
            json={"decision": "yolo"},
        )
        assert r.status_code == 400

    def test_answer_unknown_loop_is_404(self, client):
        r = client.post(
            "/api/escalations/loop-does-not-exist/answer",
            json={"decision": "skip"},
        )
        assert r.status_code == 404

    def test_answer_bad_decision_and_unknown_loop_is_400(self, client):
        """400-before-404 precedence: decision is validated unconditionally before
        the loop is even loaded, so an invalid decision + unknown loop combo must
        still be 400, not 404."""
        r = client.post(
            "/api/escalations/loop-does-not-exist/answer",
            json={"decision": "yolo"},
        )
        assert r.status_code == 400


class TestEscalationsContractSketch:
    def test_list_and_answer(self, client, seeded_escalation):
        loop_id = seeded_escalation["loop_id"]
        pending = client.get("/api/escalations").json()["pending"]
        assert any(e["loop_id"] == loop_id for e in pending)
        r = client.post(f"/api/escalations/{loop_id}/answer", json={"decision": "skip"})
        assert r.status_code == 200
        assert (
            client.post(f"/api/escalations/{loop_id}/answer", json={"decision": "yolo"}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/escalations/loop-does-not-exist/answer", json={"decision": "skip"}
            ).status_code
            == 404
        )
