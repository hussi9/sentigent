"""Tests for the skill-router data migration script."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from sentigent.scripts.migrate_skill_router_data import (
    parse_router_log,
    run_migration,
    PATH_TO_TASK_TYPE,
)


@pytest.fixture
def sample_jsonl(tmp_path) -> Path:
    events = [
        {
            "ts": "2026-05-01T10:00:00",
            "type": "embedding-route",
            "accepted": True,
            "path": "BROKEN",
            "skill": "superpowers:systematic-debugging",
            "rejected_skill": None,
            "confidence": 0.92,
            "avg_sim": 0.88,
            "margin": 0.15,
            "prompt_hash": "aaa111",
            "prompt_len": 42,
            "neighbors": [{"prompt": "fix the bug", "path": "BROKEN",
                           "skill": "superpowers:systematic-debugging", "sim": 0.91}],
        },
        {
            "ts": "2026-05-01T10:05:00",
            "type": "chain-start",
            "name": "broken-single",
            "steps": ["superpowers:systematic-debugging"],
            "models": ["sonnet"],
        },
        {
            "ts": "2026-05-01T10:10:00",
            "type": "embedding-skip",
            "accepted": False,
            "path": "BUILD",
            "skill": "feature-dev:feature-dev",
            "confidence": None,
            "avg_sim": 0.60,
            "margin": 0.05,
            "prompt_hash": "ccc333",
            "prompt_len": 30,
            "neighbors": [],
        },
        {
            "ts": "2026-05-01T10:15:00",
            "type": "embedding-skip",
            "accepted": False,
            "path": "OPERATE",
            "skill": None,
            "confidence": None,
            "avg_sim": 0.40,
            "margin": 0.01,
            "prompt_hash": "ddd444",
            "prompt_len": 15,
            "neighbors": [],
        },
    ]
    p = tmp_path / "skill_router_log.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events))
    return p


def test_path_to_task_type_mapping():
    assert PATH_TO_TASK_TYPE["BROKEN"] == "debug"
    assert PATH_TO_TASK_TYPE["BUILD"] == "build"
    assert PATH_TO_TASK_TYPE["OPERATE"] == "operate"


def test_parse_router_log_only_embedding_events_with_skill(sample_jsonl):
    records = parse_router_log(sample_jsonl)
    # chain-start excluded, embedding-skip with null skill excluded
    assert len(records) == 2
    hashes = {r["prompt_hash"] for r in records}
    assert "aaa111" in hashes
    assert "ccc333" in hashes
    assert "ddd444" not in hashes


def test_parse_router_log_accepted_route_is_correct(sample_jsonl):
    records = parse_router_log(sample_jsonl)
    by_hash = {r["prompt_hash"]: r for r in records}
    assert by_hash["aaa111"]["outcome"] == "correct"
    assert by_hash["ccc333"]["outcome"] == "neutral"


def test_parse_router_log_maps_path_to_task_type(sample_jsonl):
    records = parse_router_log(sample_jsonl)
    by_hash = {r["prompt_hash"]: r for r in records}
    assert by_hash["aaa111"]["task_type"] == "debug"
    assert by_hash["ccc333"]["task_type"] == "build"


def test_run_migration_inserts_seeds(tmp_path, sample_jsonl):
    from sentigent.memory.store import MemoryStore
    store = MemoryStore(
        agent_id="migration_test",
        org_id="test_org",
        db_path=str(tmp_path / "test.db"),
    )
    stats = run_migration(store, log_path=sample_jsonl)
    assert stats["inserted"] == 2
    assert stats["skipped"] == 0
    seeds = store.get_routing_seeds()
    assert len(seeds) == 2


def test_run_migration_dry_run_writes_nothing(tmp_path, sample_jsonl):
    from sentigent.memory.store import MemoryStore
    store = MemoryStore(
        agent_id="migration_test",
        org_id="test_org",
        db_path=str(tmp_path / "test.db"),
    )
    stats = run_migration(store, log_path=sample_jsonl, dry_run=True)
    assert stats["inserted"] == 2
    seeds = store.get_routing_seeds()
    assert len(seeds) == 0
