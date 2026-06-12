"""Flight summary — stats are real (read from store) and the panel renders cleanly."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.flight_summary import cumulative_stats, session_stats, render_panel


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-fs", org_id="t", db_path=Path(d) / "m.db")


def test_cumulative_on_fresh_store_is_zeroed_and_renders(store):
    c = cumulative_stats(store)
    assert c["episodes"] == 0 and c["decisions"] == 0 and c["precedents"] == 0
    panel = render_panel(c)                       # must not raise on an empty brain
    assert "FLIGHT COMPLETE" in panel
    assert "YOUR CLONE — all time" in panel


def test_cumulative_counts_real_precedents(store):
    store.add_precedent("normal", "force-push main?", "skip", "no")
    store.add_precedent("normal", "deploy?", "approve", "ok")
    assert cumulative_stats(store)["precedents"] == 2


def test_session_stats_counts_recent_precedents(store):
    store.add_precedent("normal", "x", "skip", "y")
    s = session_stats(store, since_ts=0.0)
    assert s["precedents_gained"] >= 1


def test_render_is_rewarding_with_real_numbers():
    cumulative = {
        "episodes": 89504,
        "dna": {"correct": 18, "approve": 8, "revert": 6, "reject": 3},
        "decisions": 35,
        "precedents": 11,
        "practices": 8,
        "calibration_accuracy": None,
        "cost_spent_usd": 449.01,
        "cost_calls": 26272,
    }
    session = {"auto_resolved": 6, "asked": 1, "precedents_gained": 11}
    panel = render_panel(cumulative, session, extras={"checks_green": 20})

    assert "89,504 decisions shadowed" in panel
    assert "11 learned precedents" in panel
    assert "86% autonomy" in panel          # 6 / (6+1)
    assert "+11 precedents learned" in panel
    assert "20 checks green" in panel
    assert "$449.01 tracked" in panel
    assert "correct" in panel and "████" in panel   # the DNA bar rendered
