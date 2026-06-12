"""Tests for ProfileBuilder (Phase 1, A2).

Locks the honest contract:
  - LLM path: normalizes the model output and persists source='llm'
  - fallback path: when the LLM is unreachable, writes source='explicit_only'
    and does NOT fabricate preferences
  - never raises; always returns a profile with a version
  - persisted row round-trips through the store
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.core.profile_builder import ProfileBuilder
from sentigent.intelligence import local_llm
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-profile", org_id="t-org", db_path=Path(d) / "m.db")


@pytest.fixture
def claude_md():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("## Rules\n- TypeScript first\n- Never delete files, move to .archive/\n")
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


def test_llm_path_normalizes_and_persists(monkeypatch, store, claude_md):
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(
        local_llm,
        "generate_json",
        lambda *a, **k: {
            "summary": "Ships fast, tests everything.",
            "preferences": ["autonomous execution", "API-first"],
            "coding_standards": "TypeScript first",  # scalar → coerced to list
            "never_do": ["delete files"],
            "risk_tolerance": {"deploy": "low"},
            "ask_when": ["2FA needed"],
            "junk_key": "ignored",
        },
    )
    b = ProfileBuilder(store=store, agent_id="t-profile", claude_md_path=claude_md, model="llama3:8b")
    out = b.build()

    assert out["source"] == "llm"
    assert out["version"] == 1
    assert out["coding_standards"] == ["TypeScript first"]  # coerced
    assert out["risk_tolerance"] == {"deploy": "low"}
    assert "junk_key" not in out  # normalized away

    stored = store.get_latest_operator_profile()
    assert stored is not None
    assert stored["source"] == "llm"
    assert stored["version"] == 1


def test_fallback_when_llm_unavailable_does_not_fabricate(monkeypatch, store, claude_md):
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: False)
    # generate_json must never be called on the fallback path.
    monkeypatch.setattr(
        local_llm, "generate_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    b = ProfileBuilder(store=store, agent_id="t-profile", claude_md_path=claude_md)
    out = b.build()

    assert out["source"] == "explicit_only"
    assert out["preferences"] == []  # no invented content
    assert out["never_do"] == []
    assert "not synthesized" in out["summary"].lower()
    assert out["version"] == 1


def test_missing_claude_md_falls_back(monkeypatch, store):
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: True)
    b = ProfileBuilder(
        store=store, agent_id="t-profile", claude_md_path="/nonexistent/CLAUDE.md"
    )
    out = b.build()
    # No explicit text → never call the LLM → explicit_only fallback.
    assert out["source"] == "explicit_only"


def test_versions_increment(monkeypatch, store, claude_md):
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: False)
    b = ProfileBuilder(store=store, agent_id="t-profile", claude_md_path=claude_md)
    assert b.build()["version"] == 1
    assert b.build()["version"] == 2


def test_build_never_raises_on_store_failure(monkeypatch, claude_md):
    class BrokenStore:
        def get_decision_event_counts(self):
            return {}

        def get_decision_events(self, limit=20):
            return []

        def save_operator_profile(self, *a, **k):
            raise RuntimeError("disk full")

    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: False)
    b = ProfileBuilder(store=BrokenStore(), agent_id="t-profile", claude_md_path=claude_md)
    out = b.build()  # must not raise
    assert out["version"] == -1
    assert out["source"] == "explicit_only"
