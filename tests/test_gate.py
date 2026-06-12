"""Tests for the Decision Gate."""

import pytest

from sentigent.core.gate import DecisionGate
from sentigent.core.types import (
    DecisionAction,
    Profile,
    Signal,
    SignalType,
    ValueHierarchy,
    WorldModel,
)


@pytest.fixture
def safety_first_profile() -> Profile:
    return Profile(
        name="test_safety_first",
        values=ValueHierarchy(values=[
            ("safety", 1.0),
            ("financial_safety", 1.0),
            ("speed", 0.4),
        ]),
        world_model=WorldModel(baselines={}),
    )


@pytest.fixture
def gate(safety_first_profile: Profile) -> DecisionGate:
    return DecisionGate(safety_first_profile)


def _make_signals(
    caution: float = 0.0,
    doubt: float = 0.0,
    urgency: float = 0.0,
    confidence: float = 0.5,
    frustration: float = 0.0,
) -> list[Signal]:
    return [
        Signal(type=SignalType.CAUTION, strength=caution, reason="test"),
        Signal(type=SignalType.DOUBT, strength=doubt, reason="test"),
        Signal(type=SignalType.URGENCY, strength=urgency, reason="test"),
        Signal(type=SignalType.CONFIDENCE, strength=confidence, reason="test"),
        Signal(type=SignalType.FRUSTRATION, strength=frustration, reason="test"),
    ]


class TestDecisionGate:

    def test_all_clear_proceeds(self, gate: DecisionGate) -> None:
        signals = _make_signals(caution=0.0, doubt=0.0, confidence=0.5)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.PROCEED

    def test_high_confidence_proceeds(self, gate: DecisionGate) -> None:
        signals = _make_signals(confidence=0.95)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.PROCEED

    def test_high_caution_escalates(self, gate: DecisionGate) -> None:
        signals = _make_signals(caution=0.85)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.ESCALATE

    def test_moderate_caution_slows_down(self, gate: DecisionGate) -> None:
        signals = _make_signals(caution=0.5)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.SLOW_DOWN

    def test_doubt_enriches(self, gate: DecisionGate) -> None:
        signals = _make_signals(doubt=0.6)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.ENRICH

    def test_frustration_escalates(self, gate: DecisionGate) -> None:
        signals = _make_signals(frustration=0.8)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.ESCALATE

    def test_caution_overrides_urgency_when_safety_first(
        self, gate: DecisionGate
    ) -> None:
        """When safety > speed in values, high caution should escalate even with high urgency."""
        signals = _make_signals(caution=0.85, urgency=0.9)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.ESCALATE

    def test_frustration_takes_priority(self, gate: DecisionGate) -> None:
        """Frustration should trigger escalation even if other signals are normal."""
        signals = _make_signals(caution=0.2, doubt=0.1, frustration=0.8)
        action, reason = gate.decide(signals)
        assert action == DecisionAction.ESCALATE
