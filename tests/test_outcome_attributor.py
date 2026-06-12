"""Tests for OutcomeAttributor absence-inference (Phase 0 honest-foundation).

Locks the rule that *absence of a complaint is NOT a 'correct' signal* — it must
attribute 'neutral'. Previously check_absence_attribution() returned 'correct'
(confidence 0.6) just because the absence window elapsed: the silent background
version of the "tool didn't error = correct" lie. This path had ZERO coverage
before this file. See docs/plans/2026-06-03-operator-autopilot-design.md (G1).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sentigent.learning.outcome import OutcomeAttributor


def _trace(outcome=None, age_hours=100.0, confidence=0.9, trace_id="t1"):
    """Minimal duck-typed trace: only the attrs check_absence_attribution reads."""
    return SimpleNamespace(
        trace_id=trace_id,
        outcome=outcome,
        timestamp=datetime.now(timezone.utc) - timedelta(hours=age_hours),
        confidence_at_decision=confidence,
    )


def test_absence_after_window_is_neutral_not_correct():
    """The core honest-foundation rule: window elapsed + no complaint => neutral."""
    attr = OutcomeAttributor(absence_window_hours=48, auto_correct_confidence=0.7)
    result = attr.check_absence_attribution(_trace())
    assert result is not None
    assert result["outcome"] == "neutral", (
        "absence of a complaint must NOT be fabricated into 'correct'"
    )
    assert result["confidence"] == 0.0
    assert result["source"] == "absence_inference"


def test_absence_before_window_returns_none():
    attr = OutcomeAttributor(absence_window_hours=48, auto_correct_confidence=0.7)
    assert attr.check_absence_attribution(_trace(age_hours=1.0)) is None


def test_absence_low_confidence_returns_none():
    attr = OutcomeAttributor(absence_window_hours=48, auto_correct_confidence=0.7)
    assert attr.check_absence_attribution(_trace(confidence=0.3)) is None


def test_absence_already_has_outcome_returns_none():
    attr = OutcomeAttributor(absence_window_hours=48, auto_correct_confidence=0.7)
    assert attr.check_absence_attribution(_trace(outcome="correct")) is None
