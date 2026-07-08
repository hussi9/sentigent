"""Baseline recompute must be throttled, and baseline_history bounded.

Regression guard for the 2026-07-07 principal review finding: record_outcome
called update_baselines_from_episodes() unconditionally — a full scan of all
episodes' JSON context on every hooked tool call, plus an unbounded
baseline_history insert per metric (160k rows on the live brain).
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

import pytest

from sentigent.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="t-throttle", org_id="t", db_path=str(tmp_path / "m.db"))


def _seed_episodes(store: MemoryStore, n: int = 10) -> None:
    """Insert graded episodes with numeric context directly (schema-level)."""
    conn = sqlite3.connect(store.db_path)
    try:
        for i in range(n):
            conn.execute(
                """
                INSERT INTO episodes
                    (trace_id, agent_id, org_id, timestamp, task, context,
                     agent_state, signals, decision, reason, outcome)
                VALUES (?, ?, ?, ?, ?, ?, '{}', '{}', 'proceed', '', 'correct')
                """,
                (
                    str(uuid.uuid4()),
                    store.agent_id,
                    store.org_id,
                    f"2026-07-07T00:00:{i:02d}+00:00",
                    "edit file",
                    json.dumps({"lines_changed": i + 1}),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_forced_recompute_runs_and_returns_true(store):
    _seed_episodes(store)
    assert store.update_baselines_from_episodes(force=True) is True


def test_unforced_recompute_is_throttled(store):
    _seed_episodes(store)
    assert store.update_baselines_from_episodes(force=True) is True
    # Immediately again, unforced: inside the throttle window — no recompute.
    assert store.update_baselines_from_episodes() is False


def test_unforced_recompute_runs_after_window(store, monkeypatch):
    _seed_episodes(store)
    assert store.update_baselines_from_episodes(force=True) is True
    # Simulate the throttle window having elapsed.
    store._last_baseline_recompute = store._last_baseline_recompute.replace(year=2020)
    assert store.update_baselines_from_episodes() is True


def test_baseline_history_is_bounded(store):
    _seed_episodes(store)
    for _ in range(60):
        assert store.update_baselines_from_episodes(force=True) is True
    conn = sqlite3.connect(store.db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM baseline_history WHERE metric_name = 'lines_changed'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count <= MemoryStore.BASELINE_HISTORY_KEEP


def test_prune_baseline_history_direct(store):
    _seed_episodes(store)
    # Bypass retention by inserting history rows directly.
    conn = sqlite3.connect(store.db_path)
    try:
        for i in range(80):
            conn.execute(
                """
                INSERT INTO baseline_history
                    (org_id, agent_id, metric_name, baseline_data, sample_size, recorded_at)
                VALUES (?, ?, 'lines_changed', '{}', 10, ?)
                """,
                (store.org_id, store.agent_id, f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    deleted = store.prune_baseline_history(keep_per_metric=50)
    assert deleted == 30

    conn = sqlite3.connect(store.db_path)
    try:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM baseline_history WHERE metric_name = 'lines_changed'"
        ).fetchone()[0]
        # The newest rows are the ones kept.
        newest = conn.execute(
            "SELECT MAX(recorded_at) FROM baseline_history WHERE metric_name = 'lines_changed'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 50
    assert newest == "2026-01-01T00:01:19+00:00"
