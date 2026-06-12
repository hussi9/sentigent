"""Tests for cost_tracker — model prices, event building, summaries."""
from __future__ import annotations
import pytest
from sentigent.telemetry.cost_tracker import (
    compute_cost,
    compute_savings,
    build_cost_event,
    CostTracker,
    MODEL_PRICES,
    BASELINE_MODEL,
)


def test_compute_cost_haiku_cheaper_than_opus():
    haiku = compute_cost("haiku", 1_000_000, 1_000_000)
    opus = compute_cost("opus", 1_000_000, 1_000_000)
    assert haiku < opus


def test_compute_cost_zero_tokens_is_zero():
    assert compute_cost("sonnet", 0, 0) == 0.0


def test_compute_cost_sonnet_known_price():
    # 1M input tokens at $3/M = $3.00
    cost = compute_cost("sonnet", 1_000_000, 0)
    assert abs(cost - 3.0) < 0.001


def test_compute_savings_cheaper_model_yields_positive():
    savings = compute_savings("haiku", 100_000, 50_000)
    assert savings > 0


def test_compute_savings_opus_yields_zero():
    # Opus IS the baseline, so savings must be zero
    savings = compute_savings(BASELINE_MODEL, 100_000, 50_000)
    assert savings == 0.0


def test_build_cost_event_sets_all_fields():
    ev = build_cost_event(
        trace_id="t1",
        agent_id="agent1",
        model="haiku",
        input_tokens=10_000,
        output_tokens=5_000,
        tool_name="Bash",
    )
    assert ev.trace_id == "t1"
    assert ev.agent_id == "agent1"
    assert ev.model == "haiku"
    assert ev.cost_usd > 0
    assert ev.baseline_cost_usd > ev.cost_usd
    assert ev.savings_usd > 0
    assert ev.tool_name == "Bash"


def test_cost_tracker_summary_aggregates_events():
    tracker = CostTracker(agent_id="test")
    for _ in range(3):
        ev = build_cost_event("t", "test", "haiku", 10_000, 5_000)
        tracker.record(ev)
    summary = tracker.summary()
    assert summary["event_count"] == 3
    assert summary["total_savings_usd"] > 0
    assert summary["savings_pct"] > 0


def test_cost_tracker_flush_clears_buffer():
    tracker = CostTracker(agent_id="test")
    tracker.record(build_cost_event("t", "test", "haiku", 10_000, 5_000))
    events = tracker.flush()
    assert len(events) == 1
    assert tracker.summary()["event_count"] == 0


def test_all_model_aliases_present():
    for alias in ["opus", "sonnet", "haiku"]:
        assert alias in MODEL_PRICES
