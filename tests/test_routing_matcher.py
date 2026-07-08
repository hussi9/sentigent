"""Tests for the embedding-based routing matcher."""
from __future__ import annotations
import pytest

pytest.importorskip("sentence_transformers", reason="embeddings extra not installed")

from sentigent.routing.matcher import match_seeds, RouteMatch, MATCH_THRESHOLD
from sentigent.routing.embeddings import encode_list


@pytest.fixture
def store_with_seeds(tmp_path):
    from sentigent.memory.store import MemoryStore
    store = MemoryStore(
        agent_id="test_agent",
        org_id="test_org",
        db_path=str(tmp_path / "test.db"),
    )
    seeds = [
        {
            "prompt_hash": "debug1",
            "prompt_text": "fix the authentication bug causing 500 errors",
            "task_type": "debug",
            "skill": "superpowers:systematic-debugging",
            "agent": "debugger",
            "model": "sonnet",
            "confidence": 0.90,
            "outcome": "correct",
        },
        {
            "prompt_hash": "build1",
            "prompt_text": "build a new user registration feature with email verification",
            "task_type": "build",
            "skill": "feature-dev:feature-dev",
            "agent": "feature-dev:code-architect",
            "model": "sonnet",
            "confidence": 0.85,
            "outcome": "correct",
        },
        {
            "prompt_hash": "bad1",
            "prompt_text": "fix the broken login form",
            "task_type": "debug",
            "skill": "superpowers:systematic-debugging",
            "agent": "debugger",
            "model": "sonnet",
            "confidence": 0.60,
            "outcome": "incorrect",
        },
    ]
    for s in seeds:
        store.insert_routing_seed(
            prompt_hash=s["prompt_hash"],
            prompt_text=s["prompt_text"],
            task_type=s["task_type"],
            skill=s["skill"],
            agent=s["agent"],
            model=s["model"],
            confidence=s["confidence"],
            avg_sim=s["confidence"],
            margin=0.1,
            neighbors=[],
            embedding=encode_list(s["prompt_text"]),
            outcome=s["outcome"],
        )
    return store


def test_match_returns_route_match_objects(store_with_seeds):
    results = match_seeds("fix the auth bug", store_with_seeds)
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, RouteMatch)


def test_match_excludes_incorrect_outcomes(store_with_seeds):
    results = match_seeds("fix the broken login form", store_with_seeds)
    for r in results:
        assert r.outcome != "incorrect"


def test_match_returns_empty_for_blank_text(store_with_seeds):
    assert match_seeds("", store_with_seeds) == []
    assert match_seeds("   ", store_with_seeds) == []


def test_match_debug_query_returns_debug_skill(store_with_seeds):
    results = match_seeds("there is a crash in the authentication module", store_with_seeds)
    if results:
        assert results[0].skill == "superpowers:systematic-debugging"


def test_match_results_sorted_by_confidence_descending(store_with_seeds):
    results = match_seeds("debug the error in production", store_with_seeds)
    scores = [r.confidence for r in results]
    assert scores == sorted(scores, reverse=True)


def test_match_all_results_above_threshold(store_with_seeds):
    results = match_seeds("fix the authentication bug", store_with_seeds)
    for r in results:
        assert r.confidence >= MATCH_THRESHOLD
