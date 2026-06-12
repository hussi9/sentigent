"""Tests for the Autonomy Receipt — deterministic, no model.

Seeds a temp store with a mixed run (clone-resolved steps + one human escalation)
and asserts the receipt totals and the autonomy rate.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.receipt import build_receipt, render_markdown


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-rcpt", org_id="t", db_path=Path(d) / "m.db")


def _seed_run(store, *, n_steps: int, clone_steps: int, escalate: bool) -> int:
    """Seed a plan + run with n_steps step_done events (clone_steps of them
    resolver-sourced) and optionally one answered escalation."""
    plan_id = store.save_plan(goal="Ship the receipt", source="test")
    run_id = store.start_run(plan_id, autonomy_level="trusted", budget_usd=2.0)
    for i in range(n_steps):
        source = "resolver" if i < clone_steps else "gate"
        payload = {
            "step": f"step {i+1}",
            "verdict": {"decision": "continue", "confidence": 0.9,
                        "reason": "as I'd do it", "source": source},
            "checkpoint": "", "note": "",
        }
        store.add_run_event(run_id, "step_done", payload, step_id=None)
    if escalate:
        eid = store.add_escalation(
            run_id, "delete the staging db?",
            context={"category": "risk_ceiling",
                     "clone_attempt": {"decision": "approve", "confidence": 0.5}},
            risk=0.8,
        )
        store.answer_escalation(eid, "skip")
    return run_id


def test_receipt_totals_and_autonomy_rate(store):
    # 4 steps resolved (2 by clone, 2 by gate) + 1 human escalation.
    run_id = _seed_run(store, n_steps=4, clone_steps=2, escalate=True)
    r = build_receipt(store, [run_id])
    run = r["runs"][0]
    assert run["auto_resolved"] == 4
    assert run["asked"] == 1
    assert run["autonomy_rate"] == pytest.approx(4 / 5)
    # decided_by attribution flows through.
    assert sum(1 for s in run["steps"] if s["decided_by"] == "clone") == 2
    assert sum(1 for s in run["steps"] if s["decided_by"] == "gate") == 2
    assert run["asks"][0]["decision"] == "skip"
    assert run["asks"][0]["clone_had_attempt"] is True
    # totals mirror the single run.
    assert r["totals"]["autonomy_rate"] == pytest.approx(4 / 5)


def test_full_autonomy_when_no_escalations(store):
    run_id = _seed_run(store, n_steps=3, clone_steps=3, escalate=False)
    r = build_receipt(store, [run_id])
    assert r["runs"][0]["autonomy_rate"] == 1.0
    assert r["totals"]["asked"] == 0


def test_render_markdown_is_scannable(store):
    run_id = _seed_run(store, n_steps=2, clone_steps=1, escalate=True)
    md = render_markdown(build_receipt(store, [run_id]))
    assert "Autonomy receipt" in md
    assert "Autonomy this run" in md
    assert "paged you" in md


def test_missing_run_is_skipped(store):
    r = build_receipt(store, [9999])
    assert r["runs"] == []
    assert r["totals"]["autonomy_rate"] == 1.0
