"""Tests for the Memory Store."""

import os
import tempfile

import pytest

from sentigent.core.types import DecisionAction, Trace
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    db_path = os.path.join(tempfile.gettempdir(), "test_memory.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    s = MemoryStore(agent_id="test_agent", org_id="test_org", db_path=db_path)
    yield s
    if os.path.exists(db_path):
        os.remove(db_path)


class TestEpisodicMemory:

    def test_store_and_count(self, store: MemoryStore) -> None:
        trace = Trace(
            trace_id="test-001",
            agent_id="test_agent",
            task="Process refund for $500",
            context={"amount": 500},
            signals={"caution": 0.1},
            decision=DecisionAction.PROCEED,
            reason="Normal operation",
        )
        store.store_episode(trace)
        assert store.get_episode_count() == 1

    def test_record_outcome(self, store: MemoryStore) -> None:
        trace = Trace(
            trace_id="test-002",
            agent_id="test_agent",
            task="Process refund",
            context={},
            signals={},
            decision=DecisionAction.PROCEED,
            reason="test",
        )
        store.store_episode(trace)
        store.record_outcome("test-002", "correct", "Verified by human")

        stats = store.get_outcome_stats()
        assert stats.get("correct") == 1

    def test_find_similar_episodes(self, store: MemoryStore) -> None:
        # Store some episodes
        for i in range(5):
            trace = Trace(
                trace_id=f"test-refund-{i}",
                agent_id="test_agent",
                task="Process refund for customer",
                context={"amount": 100 * (i + 1)},
                signals={"caution": 0.1},
                decision=DecisionAction.PROCEED,
                reason="test",
            )
            store.store_episode(trace)
            store.record_outcome(f"test-refund-{i}", "correct")

        # Search for similar
        similar = store.find_similar_episodes("Process refund request")
        assert len(similar) > 0
        assert similar[0]["outcome"] == "correct"


class TestBaselineLearning:

    def test_baselines_computed_from_episodes(self, store: MemoryStore) -> None:
        # Store enough episodes to trigger baseline computation
        for i in range(20):
            trace = Trace(
                trace_id=f"test-baseline-{i}",
                agent_id="test_agent",
                task=f"Process refund #{i}",
                context={"amount": 500 + (i * 50)},  # 500 to 1450
                signals={},
                decision=DecisionAction.PROCEED,
                reason="test",
            )
            store.store_episode(trace)
            store.record_outcome(f"test-baseline-{i}", "correct")

        store.update_baselines_from_episodes()
        baselines = store.get_baselines()

        assert "amount" in baselines
        assert baselines["amount"].sample_size == 20
        assert baselines["amount"].source == "layer_1"
        # Median should be around 975 (midpoint of 500-1450)
        assert 800 < baselines["amount"].median < 1200

    def test_no_baselines_with_few_episodes(self, store: MemoryStore) -> None:
        # Only 3 episodes — not enough for baselines
        for i in range(3):
            trace = Trace(
                trace_id=f"test-few-{i}",
                agent_id="test_agent",
                task=f"Refund #{i}",
                context={"amount": 100},
                signals={},
                decision=DecisionAction.PROCEED,
                reason="test",
            )
            store.store_episode(trace)
            store.record_outcome(f"test-few-{i}", "correct")

        store.update_baselines_from_episodes()
        baselines = store.get_baselines()
        # Should not have computed baselines (need >= 5 episodes)
        assert "amount" not in baselines
