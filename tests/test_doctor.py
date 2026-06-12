"""Doctor health check — proves it flags the exact silent failures from the code review."""
from __future__ import annotations

import tempfile
import time
import sqlite3
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.doctor import health_report


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-doc", org_id="t", db_path=Path(d) / "m.db")


def _answer_an_escalation(store, question: str, decision: str) -> int:
    store.get_escalations()
    conn = sqlite3.connect(store.db_path)
    cur = conn.execute(
        "INSERT INTO escalations (run_id, ts, question, context, status) VALUES (?,?,?,?,?)",
        (1, time.time(), question, "{}", "open"))
    conn.commit()
    eid = int(cur.lastrowid)
    conn.close()
    store.answer_escalation(eid, decision)
    return eid


def test_empty_brain_is_healthy(store):
    rep = health_report(store)
    assert rep["ok"] is True
    assert rep["learn_loop_ok"] is True   # 0 answered → no symptom
    assert rep["warnings"] == []


def test_flags_stale_learn_loop(store):
    # Answered escalations but no precedents → the exact stale-server symptom.
    _answer_an_escalation(store, "Step 2 not verified", "skip")
    _answer_an_escalation(store, "Step 3 not verified", "approve")
    rep = health_report(store)
    assert rep["answered_escalations"] == 2
    assert rep["precedents"] == 0
    assert rep["learn_loop_ok"] is False
    assert rep["ok"] is False
    assert any("learn write-back isn't firing" in w for w in rep["warnings"])


def test_flags_partial_staleness(store):
    # The improved signal (dry-run backfill) must catch the case a bare precedents==0 misses:
    # some answers learned, others not. Here one escalation is learned, two are left stale.
    from sentigent.operator.backfill import backfill_precedents
    _answer_an_escalation(store, "learned one", "approve")
    backfill_precedents(store)                      # closes only the first
    _answer_an_escalation(store, "stale two", "skip")
    _answer_an_escalation(store, "stale three", "approve")
    rep = health_report(store)
    assert rep["precedents"] >= 1                    # not zero — a bare check would say "ok"
    assert rep["learn_loop_ok"] is False             # but two answers are genuinely unlearned
    assert any("not yet learned as precedents" in w for w in rep["warnings"])


def test_healthy_once_backfilled(store):
    from sentigent.operator.backfill import backfill_precedents
    _answer_an_escalation(store, "deploy?", "skip")
    backfill_precedents(store)               # close the loop
    rep = health_report(store)
    assert rep["precedents"] >= 1
    assert rep["learn_loop_ok"] is True
    # precedents but no calibration → the second (expected) warning fires
    assert any("0 calibration events" in w for w in rep["warnings"])
