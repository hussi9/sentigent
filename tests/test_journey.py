"""Tests for Journey — the 5-step clone-lifecycle capstone surface.

Locks: fully fail-soft (never raises), each stage's status tracks real signal,
current_stage = first not-done, render() is a 5-row ladder with the next move,
to_dict() shape is stable, and open escalations are surfaced. No LLM (everything
runs deterministic with use_llm=False).
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from sentigent.core import journey
from sentigent.core.journey import Journey, Stage, compute_journey
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-journey", org_id="t", db_path=Path(d) / "m.db")


_PROFILE = (
    '{"summary":"x","preferences":["a","b"],"coding_standards":["ts"],'
    '"never_do":["delete"],"ask_when":["2fa"],"risk_tolerance":{"deploy":"low"},'
    '"source":"llm"}'
)


def _decisions(store, kind="approve", n=1, domain="global"):
    for i in range(n):
        store.insert_decision_event({
            "ts": time.time(), "kind": kind, "domain": domain,
            "signal": "x", "target": f"t{i}", "source": "test", "confidence": 0.9,
        })


# ── empty store ──────────────────────────────────────────────────────────────

def test_empty_store_stage1_active_others_sensible(store):
    j = compute_journey(store)
    assert isinstance(j, Journey)
    assert len(j.stages) == 5
    s1 = j.stages[0]
    assert s1.num == 1 and s1.name == "Create clone"
    assert s1.status == "active"          # just starting
    # later stages are locked when there's no signal at all
    assert j.stages[1].status == "locked"  # Review
    assert j.stages[2].status == "locked"  # Improve
    assert j.stages[3].status == "locked"  # Reverse shadow
    assert j.stages[4].status == "locked"  # Fly
    assert j.current_stage == 1
    assert j.next_action                   # always a move
    assert j.waiting_escalations == 0


def test_never_raises_on_garbage_store():
    class Broken:
        db_path = None
        agent_id = "x"
        def __getattr__(self, name):  # every method explodes
            raise RuntimeError("boom")
    j = compute_journey(Broken())          # must not raise
    assert isinstance(j, Journey)
    assert len(j.stages) == 5
    assert j.next_action


# ── stage 1 → done once enough signal ────────────────────────────────────────

def test_stage1_locks_with_enough_decisions(store):
    _decisions(store, "approve", journey._CREATE_DONE_EVENTS, "frontend")
    j = compute_journey(store)
    assert j.stages[0].status == "done"
    assert str(journey._CREATE_DONE_EVENTS) in j.stages[0].detail or "decisions" in j.stages[0].detail
    # review now unlocks (active), no longer locked
    assert j.stages[1].status in ("active", "done")
    assert j.current_stage >= 2


# ── stage 2 reflects a saved profile ─────────────────────────────────────────

def test_saving_profile_advances_review(store):
    before = compute_journey(store)
    assert before.stages[1].status == "locked"
    store.save_operator_profile(_PROFILE, source="llm")
    after = compute_journey(store)
    # profile present → step 1 becomes active-with-profile and step 2 unlocks
    assert after.stages[1].status in ("active", "done")
    assert after.stages[1].status != "locked"


# ── stage 3 done after adopting a practice ───────────────────────────────────

def test_adopting_practice_marks_improve_done(store):
    # give it a profile + a covered review so step 2 is done first
    store.save_operator_profile(_PROFILE, source="llm")
    _decisions(store, "approve", journey._CREATE_DONE_EVENTS)
    store.add_practice("Run the full test suite before a milestone commit",
                       domain="testing", cadence="milestone")
    j = compute_journey(store)
    assert j.stages[2].status == "done"
    assert "practice" in j.stages[2].detail


# ── render() contract ────────────────────────────────────────────────────────

def test_render_is_markdown_ladder_with_all_stages_and_next_move(store):
    out = compute_journey(store).render()
    assert isinstance(out, str)
    for name in ("Create clone", "Review", "Improve", "Reverse shadow", "Fly mode"):
        assert name in out
    assert "Next move:" in out
    assert "Readiness" in out
    # ladder icons present
    assert ("✅" in out) or ("▶️" in out) or ("🔒" in out)


# ── to_dict() shape is stable ────────────────────────────────────────────────

def test_to_dict_shape_stable(store):
    d = compute_journey(store).to_dict()
    assert set(d.keys()) == {
        "readiness_pct", "current_stage", "next_action",
        "waiting_escalations", "stages",
    }
    assert isinstance(d["readiness_pct"], int)
    assert isinstance(d["current_stage"], int)
    assert isinstance(d["stages"], list) and len(d["stages"]) == 5
    for s in d["stages"]:
        assert set(s.keys()) == {"num", "name", "status", "detail"}
        assert s["status"] in ("done", "active", "locked")


# ── escalations are counted + surfaced ───────────────────────────────────────

def test_open_escalation_is_counted(store):
    plan_id = store.save_plan("ship the toggle", source="test")
    run_id = store.start_run(plan_id, autonomy_level="assisted")
    store.add_escalation(run_id, "Confirm force-push to main?", risk=0.9)
    j = compute_journey(store)
    assert j.waiting_escalations == 1
    assert "escalation" in j.render().lower()


def test_execute_run_marks_fly_done(store):
    # a run WITH a worktree path = a real execute (fly) run
    plan_id = store.save_plan("real task", source="test")
    store.start_run(plan_id, autonomy_level="autopilot", worktree="/tmp/wt-xyz")
    j = compute_journey(store)
    assert j.stages[3].status == "done"   # reverse shadow (any run)
    assert j.stages[4].status == "done"   # fly (execute run)
    # current_stage = first NOT-done; here earlier rungs are still thin, which is
    # an honest "you skipped ahead" state — it points back at the lowest gap.
    assert j.current_stage == 1


def test_dryrun_only_marks_reverse_shadow_not_fly(store):
    plan_id = store.save_plan("dry task", source="test")
    store.start_run(plan_id, autonomy_level="assisted", worktree="")  # no worktree
    j = compute_journey(store)
    assert j.stages[3].status == "done"   # reverse shadow seen
    assert j.stages[4].status == "active"  # fly not yet done, but unlocked
