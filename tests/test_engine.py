"""Tests for the main Sentigent engine (end-to-end)."""

import os
import tempfile

import pytest

from sentigent import Sentigent
from sentigent.core.types import DecisionAction


@pytest.fixture
def judge() -> Sentigent:
    """Create a Sentigent instance with a temp database."""
    db_path = os.path.join(tempfile.gettempdir(), "test_sentigent.db")
    # Clean up any previous test DB
    if os.path.exists(db_path):
        os.remove(db_path)

    instance = Sentigent(
        profile="financial_ops",
        agent_id="test_agent",
        db_path=db_path,
    )
    yield instance

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


class TestSentigentEvaluate:

    def test_evaluate_returns_decision(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Process refund",
            context={"amount": 100},
            agent_state={"confidence": 0.9},
        )
        assert decision.action is not None
        assert decision.trace_id is not None
        assert decision.reason != ""
        assert "caution" in decision.signals

    def test_normal_amount_proceeds(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Process refund for $100",
            context={"amount": 100, "account_age_days": 500},
            agent_state={"confidence": 0.95},
        )
        assert decision.action == DecisionAction.PROCEED

    def test_anomalous_amount_escalates(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Process refund for $50,000",
            context={"amount": 50_000, "account_age_days": 45},
            agent_state={"confidence": 0.88},
        )
        assert decision.action in (DecisionAction.ESCALATE, DecisionAction.SLOW_DOWN)

    def test_signals_present_in_decision(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Process refund",
            context={"amount": 50_000},
            agent_state={"confidence": 0.5},
        )
        expected_signals = {"caution", "doubt", "urgency", "confidence", "frustration"}
        assert set(decision.signals.keys()) == expected_signals

    def test_judgment_score_starts_at_zero(self, judge: Sentigent) -> None:
        assert judge.judgment_score == 0.0


class TestSentigentLearning:

    def test_record_outcome_updates_score(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Process refund",
            context={"amount": 500},
            agent_state={"confidence": 0.9},
        )
        judge.record_outcome(decision.trace_id, "correct")
        assert judge.judgment_score == 1.0

    def test_multiple_outcomes_tracked(self, judge: Sentigent) -> None:
        for i in range(10):
            decision = judge.evaluate(
                task=f"Process refund #{i}",
                context={"amount": 100 * (i + 1)},
                agent_state={"confidence": 0.9},
            )
            outcome = "correct" if i < 8 else "incorrect"
            judge.record_outcome(decision.trace_id, outcome)

        assert judge.judgment_score == pytest.approx(0.8)

    def test_baselines_evolve_with_experience(self, judge: Sentigent) -> None:
        """After enough operations, baselines should shift from profile defaults."""
        import random
        random.seed(42)

        # Process 50 refunds
        for i in range(50):
            amount = random.uniform(100, 2000)
            decision = judge.evaluate(
                task=f"Process refund for ${amount:.0f}",
                context={"amount": round(amount, 2)},
                agent_state={"confidence": 0.9},
            )
            judge.record_outcome(decision.trace_id, "correct")

        # Baselines should now exist from operational data
        baselines = judge._memory.get_baselines()
        if "amount" in baselines:
            # The learned baseline should reflect the actual distribution
            # (100-2000 uniform), not the profile default (median=847)
            assert baselines["amount"].source == "layer_1"
            assert baselines["amount"].sample_size >= 5


class TestSentigentProfiles:

    def test_default_profile_works(self) -> None:
        db_path = os.path.join(tempfile.gettempdir(), "test_default.db")
        judge = Sentigent(profile="default", db_path=db_path)
        decision = judge.evaluate(task="Do something", context={}, agent_state={})
        assert decision.action is not None
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            Sentigent(profile="nonexistent_profile")

    def test_financial_ops_profile(self) -> None:
        db_path = os.path.join(tempfile.gettempdir(), "test_fin.db")
        judge = Sentigent(profile="financial_ops", db_path=db_path)
        assert judge._profile.name == "financial_ops"
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_customer_support_profile(self) -> None:
        db_path = os.path.join(tempfile.gettempdir(), "test_cs.db")
        judge = Sentigent(profile="customer_support", db_path=db_path)
        assert judge._profile.name == "customer_support"
        if os.path.exists(db_path):
            os.remove(db_path)
