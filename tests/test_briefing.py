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


def _episode(store, decision, when=None):
    """Insert one episode with a given decision (and optional timestamp)."""
    from datetime import datetime, timezone

    from sentigent.core.types import DecisionAction, Trace

    n = store.count_episodes()
    store.store_episode(
        Trace(
            trace_id=f"t{n}",
            agent_id=store.agent_id,
            timestamp=when or datetime.now(timezone.utc),
            task="Bash: echo hi",
            decision=DecisionAction(decision),
            reason="test",
        )
    )


def test_engagement_line_silent_when_empty(store):
    # No episodes yet → no "is it on" banner (don't claim activity that isn't there).
    assert briefing_mod.build_engagement_line(store) == ""


def test_engagement_line_shows_live_counts_and_interventions(store):
    from datetime import datetime, timedelta, timezone

    for _ in range(3):
        _episode(store, "proceed")
    _episode(store, "enrich")
    _episode(store, "slow_down")
    _episode(store, "escalate")
    # One old episode that should NOT count toward the last-24h figure.
    _episode(store, "proceed", when=datetime.now(timezone.utc) - timedelta(days=3))

    line = briefing_mod.build_engagement_line(store)
    assert "Sentigent is live" in line
    assert "7 decisions recorded" in line  # lifetime = all 7
    assert "6 actions checked in the last 24h" in line  # excludes the 3-day-old one
    # Interventions = enrich + slow_down + escalate (proceed is not an intervention).
    assert "3 interventions" in line
    assert "1 enrich" in line and "1 slow-down" in line and "1 escalate" in line


def test_count_episodes_since_is_inclusive_and_bounded(store):
    from datetime import datetime, timedelta, timezone

    _episode(store, "proceed", when=datetime.now(timezone.utc) - timedelta(hours=1))
    _episode(store, "proceed", when=datetime.now(timezone.utc) - timedelta(days=2))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    assert store.count_episodes_since(cutoff) == 1


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
