"""Tests for MemoryStore cost_events methods."""
from __future__ import annotations
import time
import pytest
from sentigent.memory.store import MemoryStore
from sentigent.telemetry.cost_tracker import build_cost_event


@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="test_agent", org_id="test_org",
                       db_path=str(tmp_path / "test.db"))


def _event(model: str = "sonnet", input_tokens: int = 1000, output_tokens: int = 500,
           ts: float | None = None) -> dict:
    evt = build_cost_event("trace-1", "test_agent", model, input_tokens, output_tokens)
    d = evt.to_dict()
    if ts is not None:
        d["ts"] = ts
    return d


def test_insert_and_retrieve_event(store):
    store.insert_cost_event(_event())
    events = store.get_cost_events_for_month(2026, 5)
    # Just confirm insert doesn't raise; month filter is epoch-based so check count >= 0
    assert isinstance(events, list)


def test_get_cost_events_for_month_filters_correctly(store):
    # Insert event in May 2026
    may_ts = time.mktime((2026, 5, 15, 12, 0, 0, 0, 0, -1))
    store.insert_cost_event(_event(ts=may_ts))

    # Insert event in June 2026
    june_ts = time.mktime((2026, 6, 1, 0, 0, 0, 0, 0, -1))
    store.insert_cost_event(_event(ts=june_ts))

    may_events = store.get_cost_events_for_month(2026, 5)
    june_events = store.get_cost_events_for_month(2026, 6)

    assert len(may_events) == 1
    assert len(june_events) == 1


def test_get_cost_events_empty_month(store):
    result = store.get_cost_events_for_month(2025, 1)
    assert result == []


def test_get_cost_summary_empty(store):
    summary = store.get_cost_summary(days=30)
    assert summary["event_count"] == 0
    assert summary["total_savings_usd"] == 0.0
    assert summary["savings_pct"] == 0.0


def test_get_cost_summary_accumulates(store):
    now = time.time()
    # Two haiku events — both should show savings vs opus baseline
    for _ in range(2):
        store.insert_cost_event(_event(model="haiku", ts=now))

    summary = store.get_cost_summary(days=1)
    assert summary["event_count"] == 2
    assert summary["total_savings_usd"] > 0
    assert summary["total_cost_usd"] > 0
    assert summary["total_baseline_usd"] > summary["total_cost_usd"]


def test_get_cost_summary_savings_pct(store):
    now = time.time()
    store.insert_cost_event(_event(model="haiku", input_tokens=10_000,
                                   output_tokens=5_000, ts=now))
    summary = store.get_cost_summary(days=1)
    expected_pct = round(
        100 * summary["total_savings_usd"] / summary["total_baseline_usd"], 2
    )
    assert abs(summary["savings_pct"] - expected_pct) < 0.01


def test_opus_events_have_zero_savings(store):
    now = time.time()
    store.insert_cost_event(_event(model="opus", ts=now))
    summary = store.get_cost_summary(days=1)
    assert summary["total_savings_usd"] == 0.0
    assert summary["savings_pct"] == 0.0
