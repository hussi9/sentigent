"""Tests for backfill_precedents — deterministic, no model.

Proves the learning loop actually closes: answered escalations become precedents, and re-running
is a no-op (idempotent). This is the regression guard for the D-010 code-review finding.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.backfill import backfill_precedents


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-bf", org_id="t", db_path=Path(d) / "m.db")


def _add_escalation(store, question: str) -> int:
    """Insert an open escalation directly, then return its id."""
    store.get_escalations()  # ensures the operator_runs/escalations tables exist
    conn = sqlite3.connect(store.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO escalations (run_id, ts, question, context, status) VALUES (?,?,?,?,?)",
            (1, time.time(), question, "{}", "open"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_backfill_closes_the_loop_and_is_idempotent(store):
    # Two answered blockers + one still open.
    e1 = _add_escalation(store, "HARD RULE: git push --force origin main")
    e2 = _add_escalation(store, "Step 2 not verified after 2 attempts: build demo")
    _open = _add_escalation(store, "Step 3 still in flight")
    store.answer_escalation(e1, "skip")
    store.answer_escalation(e2, "approve")

    assert len(store.get_precedents()) == 0  # nothing learned yet

    res = backfill_precedents(store)
    assert res["answered"] == 2          # the open one is not counted
    assert res["created"] == 2
    assert res["errors"] == 0
    precs = store.get_precedents()
    assert len(precs) == 2
    decisions = {p["decision"] for p in precs}
    assert "skip" in decisions and "approve" in decisions

    # Re-run: idempotent — no duplicates.
    res2 = backfill_precedents(store)
    assert res2["created"] == 0
    assert res2["skipped_already_learned"] == 2
    assert len(store.get_precedents()) == 2


def test_same_blocker_different_decisions_are_both_kept(store):
    """Regression (D-014): the same blocker answered two ways is TWO precedents, not one.

    Keying idempotency on blocker text alone silently dropped the second answer — found by a
    2026-06-12 self-review of the backfill module."""
    e1 = _add_escalation(store, "Build public/demo.html")   # identical blocker text
    e2 = _add_escalation(store, "Build public/demo.html")
    store.answer_escalation(e1, "approve")
    store.answer_escalation(e2, "skip")

    res = backfill_precedents(store)
    assert res["created"] == 2                              # both decisions survive
    decisions = sorted(p["decision"] for p in store.get_precedents())
    assert decisions == ["approve", "skip"]

    # Idempotent: re-running creates no duplicates even with the colliding blocker text.
    res2 = backfill_precedents(store)
    assert res2["created"] == 0
    assert len(store.get_precedents()) == 2


def test_dry_run_writes_nothing(store):
    e = _add_escalation(store, "deploy to prod?")
    store.answer_escalation(e, "skip")

    res = backfill_precedents(store, dry_run=True)
    assert res["created"] == 1 and res["dry_run"] is True
    assert len(store.get_precedents()) == 0  # dry run wrote nothing
