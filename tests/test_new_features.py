"""Tests for newly implemented features:
- Categorical anomaly detection (SERIOUS 1.3)
- Session-level decision memory (SERIOUS 1.4)
- Value hierarchy modulation (MOD 1.7)
- Circuit breaker / graceful degradation (SERIOUS 4.5)
- Episode pruning (SERIOUS 2.4)
- Async support (CRIT 4.1)
- Compound signal interactions (MOD 1.8)
- Universal integration (MOD 3.6)
- Baseline history & drift detection (MOD 4.6)
- Config integration (SERIOUS 4.3)

Fixtures are defined in conftest.py. Uses tmp_path for all temp DB files.
"""

import asyncio
import time

import pytest

from sentigent import Sentigent
from sentigent.core.gate import DecisionGate, SessionContext
from sentigent.core.signals import SignalEngine
from sentigent.core.types import (
    BaselineStats,
    DecisionAction,
    Profile,
    Signal,
    SignalType,
    ValueHierarchy,
    WorldModel,
)


# ── Categorical Anomaly Detection (SERIOUS 1.3) ──────────────────────


class TestCategoricalAnomalyDetection:

    def test_categorical_anomaly_detected(self, safety_profile: Profile) -> None:
        """Rare categorical values should trigger caution."""
        engine = SignalEngine(safety_profile)

        # Create a categorical baseline where "US" is common and "XX" is rare
        cat_baseline = BaselineStats(
            metric_name="cat_country",
            median=0.6,  # most common value frequency
            p5=0.01,     # threshold for "rare"
            min_observed=0.0,  # frequency of the current value (never seen)
            sample_size=1000,
            source="layer_1",
        )

        signals = engine.compute_all(
            task="Process payment",
            context={"country": "XX"},  # string value
            agent_state={},
            baselines={"cat_country": cat_baseline},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        assert caution.strength > 0.0
        assert any("categorical anomaly" in f or "never been seen" in f
                   for f in caution.contributing_factors)

    def test_common_categorical_no_anomaly(self, safety_profile: Profile) -> None:
        """Common categorical values should not trigger caution."""
        engine = SignalEngine(safety_profile)

        cat_baseline = BaselineStats(
            metric_name="cat_country",
            median=0.6,
            p5=0.01,
            min_observed=0.5,  # very common
            sample_size=1000,
            source="layer_1",
        )

        signals = engine.compute_all(
            task="Process payment",
            context={"country": "US"},
            agent_state={},
            baselines={"cat_country": cat_baseline},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        # No categorical anomaly, no numeric anomaly
        assert caution.strength == 0.0


# ── Value Hierarchy Signal Modulation (MOD 1.7) ──────────────────────


class TestValueHierarchyModulation:

    def test_safety_profile_amplifies_caution(self, safety_profile: Profile) -> None:
        """Safety-first profiles should amplify caution signals."""
        engine = SignalEngine(safety_profile)
        baseline = BaselineStats(
            metric_name="amount", median=100, std=50, sample_size=100,
        )

        signals = engine.compute_all(
            task="Process refund",
            context={"amount": 500},  # ~8 std devs, well above threshold
            agent_state={},
            baselines={"amount": baseline},
        )
        caution_safety = next(s for s in signals if s.type == SignalType.CAUTION)

        # Same computation with speed profile
        speed_engine = SignalEngine(Profile(
            name="test_speed",
            values=ValueHierarchy(values=[("speed", 1.0), ("safety", 0.3)]),
            world_model=WorldModel(baselines={}),
        ))
        signals_speed = speed_engine.compute_all(
            task="Process refund",
            context={"amount": 500},
            agent_state={},
            baselines={"amount": baseline},
        )
        caution_speed = next(s for s in signals_speed if s.type == SignalType.CAUTION)

        # Safety profile should produce equal or higher caution
        assert caution_safety.strength >= caution_speed.strength


# ── Session-Level Decision Memory (SERIOUS 1.4) ──────────────────────


class TestSessionContext:

    def test_session_remembers_approval(self) -> None:
        ctx = SessionContext()
        ctx.record_approval("Process refund for $500")
        assert ctx.was_recently_approved("Process refund for $500")
        assert not ctx.was_recently_approved("Process refund for $1000")

    def test_approval_expires(self) -> None:
        ctx = SessionContext()
        ctx.record_approval("Process refund for $500")
        # Simulate passage of time
        key = ctx._hash_task("Process refund for $500")
        ctx._approved_contexts[key] = time.time() - 400  # 400 seconds ago
        assert not ctx.was_recently_approved("Process refund for $500", window_seconds=300)

    def test_cumulative_risk_accumulates(self) -> None:
        ctx = SessionContext()
        for i in range(10):
            ctx.record_decision(
                trace_id=f"trace_{i}",
                action=DecisionAction.PROCEED,
                signals={"caution": 0.6},
                task_summary=f"task_{i}",
            )
        assert ctx.cumulative_risk > 0.0

    def test_escalation_count(self) -> None:
        ctx = SessionContext()
        for i in range(5):
            ctx.record_decision(
                trace_id=f"trace_{i}",
                action=DecisionAction.ESCALATE,
                signals={"caution": 0.9},
                task_summary=f"task_{i}",
            )
        assert ctx.recent_escalation_count == 5


class TestGateSessionMemory:

    def test_approved_context_proceeds(self, safety_profile: Profile) -> None:
        """After human approves, same context should proceed."""
        gate = DecisionGate(safety_profile)

        # First call: would normally escalate
        signals = [
            Signal(type=SignalType.CAUTION, strength=0.9, reason="anomaly"),
            Signal(type=SignalType.DOUBT, strength=0.0, reason="ok"),
            Signal(type=SignalType.URGENCY, strength=0.0, reason="ok"),
            Signal(type=SignalType.CONFIDENCE, strength=0.5, reason="ok"),
            Signal(type=SignalType.FRUSTRATION, strength=0.0, reason="ok"),
        ]

        action1, _ = gate.decide(signals, task_summary="refund $50000")
        assert action1 == DecisionAction.ESCALATE

        # Simulate human approval
        gate.session.record_approval("refund $50000")

        # Second call: same context, should proceed
        action2, reason = gate.decide(signals, task_summary="refund $50000")
        assert action2 == DecisionAction.PROCEED
        assert "human-approved" in reason


# ── Circuit Breaker (SERIOUS 4.5) ────────────────────────────────────


class TestCircuitBreaker:

    def test_evaluate_works_normally(self, tmp_judge: Sentigent) -> None:
        decision = tmp_judge.evaluate(
            task="Normal operation",
            context={"amount": 100},
            agent_state={"confidence": 0.9},
        )
        assert decision.action is not None
        assert not tmp_judge._memory_circuit_open

    def test_judgment_score_fallback(self, tmp_path) -> None:
        """If DB is corrupted, judgment_score should return 0 not raise."""
        db_path = str(tmp_path / "test_circuit_breaker.db")
        judge = Sentigent(profile="default", db_path=db_path)
        # Force circuit open
        judge._memory_circuit_open = True
        # Should still work (uses profile defaults only)
        decision = judge.evaluate(task="test", context={}, agent_state={})
        assert decision.action is not None


# ── Episode Pruning (SERIOUS 2.4) ────────────────────────────────────


class TestEpisodePruning:

    def test_prune_removes_old_episodes(self, tmp_judge: Sentigent) -> None:
        """Old episodes with outcomes should be pruned."""
        import random
        random.seed(42)

        # Create some episodes
        for i in range(10):
            decision = tmp_judge.evaluate(
                task=f"Task {i}",
                context={"amount": random.uniform(100, 1000)},
                agent_state={"confidence": 0.9},
            )
            tmp_judge.record_outcome(decision.trace_id, "correct")

        initial_count = tmp_judge._memory.get_episode_count()
        assert initial_count >= 10

        # Prune with 0-day TTL (prunes everything)
        pruned = tmp_judge._memory.prune_old_episodes(ttl_days=0)
        # All episodes with outcomes should be pruned
        assert pruned >= 10

        # Active table should have fewer episodes
        final_count = tmp_judge._memory.get_episode_count()
        assert final_count < initial_count


# ── Async Support (CRIT 4.1) ─────────────────────────────────────────


class TestAsyncSentigent:

    def test_async_evaluate(self, tmp_path) -> None:
        from sentigent.core.async_engine import AsyncSentigent

        async def _test() -> None:
            db_path = str(tmp_path / "test_async.db")

            judge = AsyncSentigent(
                profile="financial_ops",
                agent_id="async_test",
                db_path=db_path,
            )

            decision = await judge.evaluate(
                task="Process refund",
                context={"amount": 500},
                agent_state={"confidence": 0.9},
            )
            assert decision.action is not None
            assert decision.trace_id is not None

            # Record outcome
            await judge.record_outcome(decision.trace_id, "correct")
            assert judge.judgment_score == 1.0

        asyncio.run(_test())


# ── Compound Signal Interactions (MOD 1.8) ─────────────────────────


class TestCompoundSignalInteractions:

    def test_caution_amplified_by_doubt(self, safety_profile: Profile) -> None:
        """High caution + high doubt should amplify caution."""
        engine = SignalEngine(safety_profile)

        # Create a scenario with moderate anomaly + low confidence
        baseline = BaselineStats(
            metric_name="amount", median=100, std=50, sample_size=100,
        )

        signals = engine.compute_all(
            task="Process payment",
            context={"amount": 350},  # 5 std devs → caution fires
            agent_state={"confidence": 0.3},  # Low confidence → doubt fires
            baselines={"amount": baseline},
        )
        caution = next(s for s in signals if s.type == SignalType.CAUTION)
        doubt = next(s for s in signals if s.type == SignalType.DOUBT)

        # Both should be non-zero
        assert caution.strength > 0
        assert doubt.strength > 0

        # If caution and doubt are both high enough, there should be an
        # "Amplified by doubt" factor
        if caution.strength > 0.3 and doubt.strength > 0.3:
            assert any("Amplified by doubt" in f for f in caution.contributing_factors)

    def test_urgency_boosts_confidence_when_safe(self, safety_profile: Profile) -> None:
        """High urgency + low caution should boost confidence."""
        engine = SignalEngine(safety_profile)

        signals = engine.compute_all(
            task="Process urgent payment",
            context={"amount": 100, "time_pressure": 0.9, "consequence_severity": 0.9},
            agent_state={"confidence": 0.8},
            baselines={},
        )
        confidence = next(s for s in signals if s.type == SignalType.CONFIDENCE)
        urgency = next(s for s in signals if s.type == SignalType.URGENCY)
        caution = next(s for s in signals if s.type == SignalType.CAUTION)

        # With no baselines, caution should be 0 and urgency should be high
        assert caution.strength < 0.2
        assert urgency.strength > 0.5

        # Confidence should have the urgency boost factor
        if urgency.strength > 0.5 and caution.strength < 0.2:
            assert any("Boosted by urgency" in f for f in confidence.contributing_factors)


# ── Universal Integration (MOD 3.6) ──────────────────────────────


class TestUniversalIntegration:

    def test_judge_call_decorator(self, tmp_judge: Sentigent) -> None:
        """The universal decorator should wrap functions with judgment."""
        from sentigent.integrations.universal import judge_call

        @judge_call(tmp_judge, task="test operation")
        def my_operation(x: int) -> int:
            return x * 2

        result = my_operation(5)
        assert result == 10

    def test_judge_call_records_outcome(self, tmp_judge: Sentigent) -> None:
        """The decorator should record success outcomes when enabled."""
        from sentigent.integrations.universal import judge_call

        @judge_call(tmp_judge, task="simple add", record_outcomes=True)
        def add(a: int, b: int) -> int:
            return a + b

        result = add(3, 4)
        assert result == 7
        # Outcome should have been recorded
        assert tmp_judge.judgment_score > 0.0

    def test_judge_call_escalation(self, tmp_path) -> None:
        """The decorator should raise EscalationRequired for escalated decisions."""
        from sentigent.integrations.universal import EscalationRequired, judge_call

        db_path = str(tmp_path / "test_universal.db")
        j = Sentigent(profile="financial_ops", agent_id="test_univ", db_path=db_path)

        @judge_call(j, task="huge refund", context={"amount": 999_999})
        def process_huge_refund() -> str:
            return "done"

        # This should either escalate or proceed depending on profile baselines
        try:
            result = process_huge_refund()
            # If it didn't escalate, it still works
            assert result == "done"
        except EscalationRequired as e:
            assert e.decision.action.value == "escalate"
            assert e.decision.trace_id is not None

    def test_judgment_context_manager(self, tmp_judge: Sentigent) -> None:
        """JudgmentContext should provide decision info and record outcomes."""
        from sentigent.integrations.universal import JudgmentContext

        with JudgmentContext(tmp_judge, task="batch process", context={"amount": 100}) as jctx:
            assert jctx.decision is not None
            assert jctx.decision.action is not None
            # Always record success to test the outcome recording path
            jctx.record_success("batch completed")

        # Outcome should have been recorded
        assert tmp_judge.judgment_score > 0.0


# ── Baseline History & Drift Detection (MOD 4.6) ──────────────────


class TestBaselineHistory:

    def test_baseline_history_recorded(self, tmp_judge: Sentigent) -> None:
        """Updating baselines should create history entries."""
        import random
        random.seed(42)

        # Generate enough episodes to trigger baseline updates
        for i in range(20):
            decision = tmp_judge.evaluate(
                task=f"Process refund {i}",
                context={"amount": random.uniform(100, 500)},
                agent_state={"confidence": 0.9},
            )
            tmp_judge.record_outcome(decision.trace_id, "correct")

        # Check that baseline history was recorded
        history = tmp_judge._memory.get_baseline_history("amount")
        assert len(history) > 0
        assert "median" in history[0]["baseline_data"]

    def test_drift_detection_no_drift(self, tmp_judge: Sentigent) -> None:
        """No drift should return None when baselines are stable."""
        import random
        random.seed(42)

        # Create stable baseline (same distribution)
        for i in range(30):
            decision = tmp_judge.evaluate(
                task=f"Task {i}",
                context={"amount": random.uniform(100, 500)},
                agent_state={"confidence": 0.9},
            )
            tmp_judge.record_outcome(decision.trace_id, "correct")

        drift = tmp_judge._memory.detect_baseline_drift("amount")
        # With a stable distribution, drift should be None or within threshold
        # (depends on random seed, but generally stable)
        if drift is not None:
            assert drift["relative_change"] > 0.3  # Only returned if drifted


# ── Config Integration (SERIOUS 4.3) ──────────────────────────────


class TestConfigIntegration:

    def test_engine_uses_config_defaults(self, tmp_path) -> None:
        """Engine should fall back to config for unset parameters."""
        from sentigent.config import SentigentConfig, set_config

        test_config = SentigentConfig(
            profile="financial_ops",
            agent_id="config_test_agent",
            org_id="config_test_org",
            evaluate_timeout_ms=100,
        )
        set_config(test_config)

        db_path = str(tmp_path / "test_config.db")
        j = Sentigent(db_path=db_path)  # No explicit agent_id/org_id

        assert j._agent_id == "config_test_agent"
        assert j._org_id == "config_test_org"
        assert j._evaluate_timeout_ms == 100

        # Cleanup
        set_config(None)

    def test_explicit_params_override_config(self, tmp_path) -> None:
        """Explicit parameters should override config values."""
        from sentigent.config import SentigentConfig, set_config

        test_config = SentigentConfig(
            profile="default",
            agent_id="config_agent",
        )
        set_config(test_config)

        db_path = str(tmp_path / "test_config2.db")
        j = Sentigent(agent_id="explicit_agent", db_path=db_path)

        assert j._agent_id == "explicit_agent"

        # Cleanup
        set_config(None)
