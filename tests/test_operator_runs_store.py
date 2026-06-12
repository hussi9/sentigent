"""Tests for the Fly-mode (Operator autopilot) persistence layer.

Locks the durable record: a plan with steps, a run, its audit log, and the
escalations it raised + answered all round-trip through MemoryStore. Tables are
created lazily on first use against a fresh db (fail-soft, no manual migration).
See docs/plans/2026-06-03-operator-autopilot-design.md (§3 data model).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-op", org_id="t", db_path=Path(d) / "m.db")


def test_full_roundtrip(store):
    # Plan + steps
    plan_id = store.save_plan("ship the feature", source="cli")
    assert plan_id > 0

    s1 = store.save_plan_step(
        plan_id, 0, "write tests", done_criteria={"suite": "green"}
    )
    s2 = store.save_plan_step(
        plan_id, 1, "implement", done_criteria='{"raw":1}', depends_on=str(s1)
    )
    assert s1 > 0 and s2 > 0

    steps = store.get_plan_steps(plan_id)
    assert [s["idx"] for s in steps] == [0, 1]
    assert steps[0]["description"] == "write tests"
    # done_criteria comes back as a stored string (caller parses)
    assert json.loads(steps[0]["done_criteria"]) == {"suite": "green"}
    assert steps[1]["depends_on"] == str(s1)
    assert steps[0]["status"] == "pending"

    store.update_plan_step_status(s1, "done", checkpoint_sha="abc123")
    steps = store.get_plan_steps(plan_id)
    assert steps[0]["status"] == "done"
    assert steps[0]["checkpoint_sha"] == "abc123"
    # update without sha leaves sha untouched
    store.update_plan_step_status(s2, "running")
    steps = store.get_plan_steps(plan_id)
    assert steps[1]["status"] == "running"
    assert steps[1]["checkpoint_sha"] == ""

    # Run
    run_id = store.start_run(
        plan_id, autonomy_level="supervised", budget_usd=5.0, worktree="/tmp/wt"
    )
    assert run_id > 0

    store.update_run(run_id, spent_usd=1.25)
    store.update_run(run_id, status="done", ended_at_now=True)

    # Audit log (newest first)
    store.add_run_event(run_id, "step_start", payload={"step": s1}, step_id=s1)
    store.add_run_event(run_id, "tool_call", payload='{"tool":"Bash"}')
    events = store.get_run_events(run_id)
    assert len(events) == 2
    assert events[0]["type"] == "tool_call"  # newest first
    assert events[1]["type"] == "step_start"
    assert events[1]["step_id"] == s1
    assert json.loads(events[1]["payload"]) == {"step": s1}

    # Escalation lifecycle
    esc_id = store.add_escalation(
        run_id,
        "delete prod data?",
        context={"path": "/db"},
        risk=0.9,
        step_id=s2,
    )
    assert esc_id > 0

    open_now = store.get_open_escalations(run_id)
    assert len(open_now) == 1
    assert open_now[0]["question"] == "delete prod data?"
    assert open_now[0]["risk"] == 0.9
    assert json.loads(open_now[0]["context"]) == {"path": "/db"}

    store.answer_escalation(esc_id, "no — abort")

    # Empty after answering
    assert store.get_open_escalations(run_id) == []
    assert store.get_open_escalations() == []

    # Verify the run row persisted the patches
    conn = sqlite3.connect(store.db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = dict(
            conn.execute(
                "SELECT * FROM operator_runs WHERE id=?", (run_id,)
            ).fetchone()
        )
    finally:
        conn.close()
    assert row["status"] == "done"
    assert row["spent_usd"] == 1.25
    assert row["ended_at"] is not None
    assert row["worktree"] == "/tmp/wt"


def test_lazy_table_creation_on_fresh_db():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "fresh.db"
        s = MemoryStore(agent_id="t-op2", org_id="t", db_path=db)
        # No tables yet — first read should create them and return empty
        assert s.get_open_escalations() == []
        assert s.get_run_events(999) == []
        assert s.get_plan_steps(999) == []

        conn = sqlite3.connect(db)
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        assert {
            "plans",
            "plan_steps",
            "operator_runs",
            "run_events",
            "escalations",
        }.issubset(tables)


def test_open_escalations_scoped_by_run(store):
    p = store.save_plan("g")
    r1 = store.start_run(p)
    r2 = store.start_run(p)
    store.add_escalation(r1, "q1")
    store.add_escalation(r2, "q2")

    assert len(store.get_open_escalations(r1)) == 1
    assert len(store.get_open_escalations(r2)) == 1
    assert len(store.get_open_escalations()) == 2
