"""Tests for billing calculator — monthly invoice computation."""
from __future__ import annotations
import pytest
from sentigent.billing.calculator import (
    compute_monthly_bill,
    format_bill,
    SUCCESS_FEE_RATE,
    PLATFORM_FEE_RATE,
    BillingPeriod,
)


def _make_events(count: int, model: str = "haiku", tokens: int = 10_000) -> list[dict]:
    from sentigent.telemetry.cost_tracker import build_cost_event
    return [
        build_cost_event(f"t{i}", "agent1", model, tokens, tokens // 2).to_dict()
        for i in range(count)
    ]


def test_empty_events_yields_zero_bill():
    period = compute_monthly_bill([], year=2026, month=5, agent_id="a", org_id="o")
    assert period.total_due_usd == 0.0
    assert period.event_count == 0


def test_haiku_savings_are_positive():
    events = _make_events(10, model="haiku")
    period = compute_monthly_bill(events, year=2026, month=5)
    assert period.total_savings_usd > 0
    assert period.savings_pct > 0


def test_opus_yields_no_savings():
    events = _make_events(5, model="opus")
    period = compute_monthly_bill(events, year=2026, month=5)
    assert period.total_savings_usd == 0.0


def test_success_fee_is_20_pct_of_savings():
    events = _make_events(10, model="haiku")
    period = compute_monthly_bill(events, year=2026, month=5)
    expected = round(period.total_savings_usd * SUCCESS_FEE_RATE, 6)
    assert abs(period.success_fee_usd - expected) < 1e-9


def test_platform_fee_is_2_pct_of_baseline():
    events = _make_events(10, model="sonnet")
    period = compute_monthly_bill(events, year=2026, month=5)
    expected = round(period.total_baseline_usd * PLATFORM_FEE_RATE, 6)
    assert abs(period.platform_fee_usd - expected) < 1e-9


def test_total_due_is_sum_of_fees():
    events = _make_events(10, model="haiku")
    period = compute_monthly_bill(events, year=2026, month=5)
    assert abs(period.total_due_usd - (period.success_fee_usd + period.platform_fee_usd)) < 1e-9


def test_format_bill_contains_key_fields():
    events = _make_events(5, model="haiku")
    period = compute_monthly_bill(events, year=2026, month=5, agent_id="myagent", org_id="myorg")
    bill_text = format_bill(period)
    assert "myagent" in bill_text
    assert "2026-05" in bill_text
    assert "Total due" in bill_text
    assert "Success fee" in bill_text


def test_billing_period_stores_year_month():
    period = compute_monthly_bill([], year=2026, month=11, agent_id="x", org_id="y")
    assert period.year == 2026
    assert period.month == 11
