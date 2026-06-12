"""Tests for the clone briefing ('The Clone Speaks') + the no-LLM review path.

The briefing runs on the SessionStart hot path, so it MUST be deterministic and
never call the LLM. These lock that contract.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.core import briefing as briefing_mod
from sentigent.core import profile_review as pr_mod
from sentigent.core.briefing import build_clone_briefing
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-brief", org_id="t", db_path=Path(d) / "m.db")


def test_empty_store_is_silent(store):
    # Nothing captured → the clone stays quiet rather than nagging.
    assert build_clone_briefing(store) == ""


def test_briefing_speaks_once_profile_exists(store):
    store.save_operator_profile(
        '{"summary":"ships fast","preferences":["autonomous"],'
        '"coding_standards":["never commit a secret"],"never_do":["delete files"],'
        '"ask_when":["2fa"],"risk_tolerance":{"deploy":"low"},"source":"llm"}',
        source="llm",
    )
    text = build_clone_briefing(store)
    assert "Your clone" in text
    assert "% ready" in text
    assert "Grow me" in text
    # mentions the in-session verbs (the interface doctrine)
    assert "clone_status" in text and "clone_adopt" in text


def test_briefing_never_calls_llm(monkeypatch, store):
    # Hard contract: SessionStart must not block on the model. If anything tries
    # to call the LLM, fail loudly.
    def _boom(*a, **k):
        raise AssertionError("briefing must not call the local LLM")

    monkeypatch.setattr(pr_mod.local_llm, "llm_available", _boom)
    monkeypatch.setattr(pr_mod.local_llm, "generate_json", _boom)
    store.save_operator_profile('{"summary":"x","preferences":["a"],"source":"llm"}', source="llm")
    text = build_clone_briefing(store)  # must not raise
    assert "Your clone" in text


def test_briefing_never_raises_on_broken_store():
    class Broken:
        def get_latest_operator_profile(self): raise RuntimeError("x")
        def get_decision_event_counts(self): raise RuntimeError("x")
        def get_practices(self, active_only=True): raise RuntimeError("x")
    assert briefing_mod.build_clone_briefing(Broken()) == ""


def test_review_use_llm_false_skips_enrichment(monkeypatch, store):
    monkeypatch.setattr(pr_mod.local_llm, "llm_available",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no llm")))
    store.add_practice("tests before commit", domain="testing", cadence="commit")
    r = pr_mod.review(store, use_llm=False)  # must not call llm_available
    assert r.source == "deterministic"
    assert r.coverage_pct >= 0
