"""Tests for MemoryStore routing_seeds methods."""
from __future__ import annotations
import pytest
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(
        agent_id="test_agent",
        org_id="test_org",
        db_path=str(tmp_path / "test_memory.db"),
    )


def test_insert_and_retrieve_routing_seed(store):
    store.insert_routing_seed(
        prompt_hash="abc123",
        prompt_text="fix the auth bug",
        task_type="debug",
        skill="superpowers:systematic-debugging",
        agent="debugger",
        model="sonnet",
        confidence=0.87,
        avg_sim=0.81,
        margin=0.12,
        neighbors=[],
        embedding=[0.1] * 384,
        outcome="correct",
    )
    seeds = store.get_routing_seeds(task_type="debug", min_confidence=0.5)
    assert len(seeds) == 1
    assert seeds[0]["skill"] == "superpowers:systematic-debugging"
    assert seeds[0]["outcome"] == "correct"


def test_update_routing_seed_outcome(store):
    store.insert_routing_seed(
        prompt_hash="xyz789",
        prompt_text="deploy to production",
        task_type="operate",
        skill="vercel:deploy",
        agent="general-purpose",
        model="sonnet",
        confidence=0.75,
        avg_sim=0.70,
        margin=0.10,
        neighbors=[],
        embedding=[0.2] * 384,
        outcome="neutral",
    )
    store.update_routing_seed_outcome(prompt_hash="xyz789", outcome="correct")
    seeds = store.get_routing_seeds(task_type="operate")
    assert seeds[0]["outcome"] == "correct"


def test_get_routing_seeds_returns_empty_for_unknown_type(store):
    seeds = store.get_routing_seeds(task_type="unknown_type")
    assert seeds == []


def test_get_all_routing_seeds_for_embedding_search(store):
    for i in range(5):
        store.insert_routing_seed(
            prompt_hash=f"hash{i}",
            prompt_text=f"task {i}",
            task_type="build",
            skill="feature-dev:feature-dev",
            agent="feature-dev:code-architect",
            model="sonnet",
            confidence=0.8,
            avg_sim=0.75,
            margin=0.1,
            neighbors=[],
            embedding=[float(i) / 10] * 384,
            outcome="correct",
        )
    all_seeds = store.get_all_routing_seeds_with_embeddings()
    assert len(all_seeds) == 5
    assert "embedding" in all_seeds[0]
    assert isinstance(all_seeds[0]["embedding"], list)
