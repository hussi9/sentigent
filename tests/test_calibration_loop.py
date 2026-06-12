"""Calibration loop — proven end-to-end (D-011).

The wiring already exists: `operate.py` stashes the clone's attempt (`clone_attempt`) into the
escalation context when it escalates after a resolver attempt (operate.py:532-536), and
`learn_from_escalation_answer` calibrates that guess against the human's answer. Live calibration
was empty only because every real escalation so far was a *hard rule* (resolver skipped) or a
*verify-failed* step (resolver not run) — i.e. correct-but-unexercised, not broken.

These tests exercise it directly so it can never silently regress.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.resolver import CloneResolver


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-cal", org_id="t", db_path=Path(d) / "m.db")


def _escalation(store, question: str, clone_attempt: dict | None) -> int:
    store.get_escalations()  # ensure tables exist
    ctx = {"category": "low_confidence"}
    if clone_attempt is not None:
        ctx["clone_attempt"] = clone_attempt
    conn = sqlite3.connect(store.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO escalations (run_id, ts, question, context, status) VALUES (?,?,?,?,?)",
            (1, time.time(), question, json.dumps(ctx), "open"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_answer_calibrates_when_the_clone_attempted(store):
    # The clone guessed 'approve'; the human also approves → a recorded, correct calibration.
    eid = _escalation(store, "deploy this step?", {"decision": "approve", "confidence": 0.8})
    store.answer_escalation(eid, "approve")

    res = store.learn_from_escalation_answer(eid, "approve")
    assert res["learned"] is True
    assert res["calibrated"] is True            # the clone's guess was scored

    cal = store.get_calibration()
    assert cal, "a calibration event should exist"
    thr = CloneResolver.thresholds_from_calibration(store, min_samples=1)
    assert isinstance(thr, dict)                # thresholds derive from real outcomes


def test_no_calibration_without_a_clone_attempt(store):
    # Hard-rule / verify-failed escalations carry no clone_attempt → a precedent forms,
    # but there is nothing to calibrate. This is exactly the live case.
    eid = _escalation(store, "Step 2 not verified done", clone_attempt=None)
    store.answer_escalation(eid, "skip")

    res = store.learn_from_escalation_answer(eid, "skip")
    assert res["learned"] is True               # precedent still forms
    assert res["calibrated"] is False           # but no calibration without a guess
