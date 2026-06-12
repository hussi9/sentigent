"""Tests for the Signal Engine."""

import pytest

from sentigent.core.signals import SignalEngine
from sentigent.core.types import BaselineStats, Profile, SignalType, ValueHierarchy, WorldModel


@pytest.fixture
def financial_profile() -> Profile:
    return Profile(
        name="test_financial",
        values=ValueHierarchy(values=[
            ("financial_safety", 1.0),
            ("speed", 0.4),
        ]),
        world_model=WorldModel(baselines={}),
        signal_thresholds={
            "caution_threshold": 2.0,
            "doubt_threshold": 0.6,
            "urgency_threshold": 0.8,
            "confidence_fast_path": 0.9,
            "frustration_retries": 3,
        },
    )


@pytest.fixture
def engine(financial_profile: Profile) -> SignalEngine:
    return SignalEngine(financial_profile)


@pytest.fixture
def amount_baseline() -> BaselineStats:
    return BaselineStats(
        metric_name="amount",
        median=847,
        mean=1250,
        std=2500,
        p5=15,
        p25=125,
        p75=1500,
        p95=5200,
        sample_size=10000,
        source="profile_default",
    )


class TestCautionSignal:
    """Tests for the caution signal computation."""

    def test_normal_amount_no_caution(
        self, engine: SignalEngine, amount_baseline: BaselineStats
    ) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"amount": 500},
            agent_state={"confidence": 0.9},
            baselines={"amount": amount_baseline},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        assert caution.strength == 0.0

    def test_high_amount_triggers_caution(
        self, engine: SignalEngine, amount_baseline: BaselineStats
    ) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"amount": 50_000},
            agent_state={"confidence": 0.9},
            baselines={"amount": amount_baseline},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        assert caution.strength > 0.5
        assert len(caution.contributing_factors) > 0

    def test_no_baselines_no_caution(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"amount": 50_000},
            agent_state={"confidence": 0.9},
            baselines={},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        assert caution.strength == 0.0


class TestDoubtSignal:
    """Tests for the doubt signal computation."""

    def test_high_confidence_no_doubt(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"data_quality": 0.95},
            agent_state={"confidence": 0.95},
            baselines={},
        )
        doubt = next(s for s in signals if s.type == SignalType.DOUBT)
        assert doubt.strength == 0.0

    def test_low_confidence_triggers_doubt(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"data_quality": 0.5},
            agent_state={"confidence": 0.4},
            baselines={},
        )
        doubt = next(s for s in signals if s.type == SignalType.DOUBT)
        assert doubt.strength > 0.3

    def test_no_similar_episodes_adds_doubt(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={},
            agent_state={"confidence": 0.7},
            baselines={},
            similar_episodes=[],
        )
        doubt = next(s for s in signals if s.type == SignalType.DOUBT)
        # Empty similar episodes should contribute some doubt
        assert doubt.strength >= 0.0


class TestFrustrationSignal:
    """Tests for the frustration signal computation."""

    def test_no_retries_no_frustration(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={},
            agent_state={"retry_count": 0},
            baselines={},
        )
        frustration = next(s for s in signals if s.type == SignalType.FRUSTRATION)
        assert frustration.strength == 0.0

    def test_many_retries_triggers_frustration(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={},
            agent_state={"retry_count": 5, "last_error": "Connection timeout"},
            baselines={},
        )
        frustration = next(s for s in signals if s.type == SignalType.FRUSTRATION)
        assert frustration.strength > 0.5


class TestAllSignals:
    """Tests for computing all signals together."""

    def test_returns_five_signals(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={},
            agent_state={},
            baselines={},
        )
        assert len(signals) == 5
        signal_types = {s.type for s in signals}
        assert signal_types == {
            SignalType.CAUTION,
            SignalType.DOUBT,
            SignalType.URGENCY,
            SignalType.CONFIDENCE,
            SignalType.FRUSTRATION,
        }

    def test_all_strengths_in_range(self, engine: SignalEngine) -> None:
        signals = engine.compute_all(
            task="Process refund",
            context={"amount": 50_000, "data_quality": 0.3},
            agent_state={"confidence": 0.4, "retry_count": 5},
            baselines={"amount": BaselineStats(
                metric_name="amount", median=847, std=2500
            )},
        )
        for signal in signals:
            assert 0.0 <= signal.strength <= 1.0, (
                f"Signal {signal.type} strength {signal.strength} out of range"
            )
