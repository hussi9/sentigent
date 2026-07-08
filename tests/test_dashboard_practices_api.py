"""Tests for the FastAPI dashboard's /api/practices endpoints (Console Task 9)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient wired to a temp per-test SQLite db via SENTIGENT_DB_PATH."""
    db_path = tmp_path / "practices_api.db"
    monkeypatch.setenv("SENTIGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTIGENT_AGENT_ID", "test_agent")
    monkeypatch.delenv("SENTIGENT_ORG_ID", raising=False)
    monkeypatch.delenv("SENTIGENT_SUPABASE_ORG_ID", raising=False)

    from sentigent.dashboard.server import app

    return TestClient(app)


class TestPracticesList:
    def test_list_empty(self, client):
        r = client.get("/api/practices")
        assert r.status_code == 200
        assert r.json() == {"practices": []}


class TestPracticesCreate:
    def test_create_returns_practice_with_defaults(self, client):
        r = client.post(
            "/api/practices",
            json={"text": "Run tests before committing", "cadence": "commit"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "Run tests before committing"
        assert body["cadence"] == "commit"
        assert body["domain"] == "global"
        assert body["enforcement"] == "warn"
        assert body["active"] is True
        assert body["times_followed"] == 0
        assert body["times_skipped"] == 0
        assert isinstance(body["id"], int)

    def test_create_appears_in_list(self, client):
        client.post("/api/practices", json={"text": "Review the diff before merge"})
        rows = client.get("/api/practices").json()["practices"]
        assert len(rows) == 1
        assert rows[0]["text"] == "Review the diff before merge"
        assert rows[0]["domain"] == "global"


class TestPracticesEnforcement:
    def test_set_enforcement_updates_level(self, client):
        pid = client.post("/api/practices", json={"text": "Write tests first"}).json()["id"]
        r = client.post(f"/api/practices/{pid}/enforcement", json={"level": "block"})
        assert r.status_code == 200
        assert r.json()["enforcement"] == "block"

        rows = client.get("/api/practices").json()["practices"]
        assert rows[0]["enforcement"] == "block"

    def test_set_enforcement_invalid_level_is_400(self, client):
        pid = client.post("/api/practices", json={"text": "Write tests first"}).json()["id"]
        r = client.post(f"/api/practices/{pid}/enforcement", json={"level": "nuke"})
        assert r.status_code == 400


class TestPracticesToggle:
    def test_toggle_flips_active(self, client):
        pid = client.post("/api/practices", json={"text": "Check accessibility"}).json()["id"]

        r = client.post(f"/api/practices/{pid}/toggle")
        assert r.status_code == 200
        assert r.json()["active"] is False

        r = client.post(f"/api/practices/{pid}/toggle")
        assert r.status_code == 200
        assert r.json()["active"] is True

    def test_toggle_unknown_id_is_404(self, client):
        r = client.post("/api/practices/999999/toggle")
        assert r.status_code == 404


class TestPracticesRoundtrip:
    def test_full_roundtrip(self, client):
        r = client.post(
            "/api/practices",
            json={"text": "Run tests before committing", "cadence": "commit"},
        )
        assert r.status_code == 200 and r.json()["enforcement"] == "warn"
        pid = r.json()["id"]

        r = client.post(f"/api/practices/{pid}/enforcement", json={"level": "block"})
        assert r.json()["enforcement"] == "block"

        assert (
            client.post(f"/api/practices/{pid}/enforcement", json={"level": "nuke"}).status_code
            == 400
        )

        rows = client.get("/api/practices").json()["practices"]
        assert rows[0]["enforcement"] == "block"
