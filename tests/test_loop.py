"""Tests for the LoopRunner (run_loop), the escalation-answer write-back, and the
calibration→threshold feedback. All deterministic: fake runner, offline gate,
stub DoD — never spawns claude or Ollama.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import gate as gate_mod
from sentigent.operator.loop import run_loop
from sentigent.operator.plan import parse_plan
from sentigent.operator.resolver import CloneResolver
from sentigent.operator.runner import TurnResult
from sentigent.operator.safety import KillSwitch


class FakeRunner:
    def drive(self, prompt, *, system="", workdir=None):
        return TurnResult(ok=True, text="did it", input_tokens=10, output_tokens=5, dry_run=True)


class StubDoD:
    """Satisfied on the `flip`-th call onward."""
    def __init__(self, flip: int):
        self.calls = 0
        self.flip = flip

    def satisfied(self, repo_path):
        self.calls += 1
        ok = self.calls >= self.flip
        return type("R", (), {"satisfied": ok, "reason": "stub-done" if ok else "not yet"})()


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(agent_id="t-loop", org_id="t", db_path=Path(d) / "m.db")
        s.save_operator_profile('{"summary":"ships fast","source":"llm"}', source="llm")
        yield s


@pytest.fixture(autouse=True)
def _offline_gate(monkeypatch):
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)


# ---- run_loop ----------------------------------------------------------------

def test_loop_stops_when_goal_done(store):
    plan = parse_plan("# g\n- [ ] add a hook\n")
    res = run_loop(store, "build it", StubDoD(flip=1), plan=plan,
                   runner_factory=lambda lap: FakeRunner(), autonomy="trusted")
    assert res.status == "done" and res.laps == 1
    assert len(res.run_ids) == 1


def test_loop_fresh_runner_per_lap(store):
    # plan_fn returns work on laps 1-2 then None; DoD never satisfied → laps run fresh.
    laps_seen = []

    def plan_fn(lap):
        laps_seen.append(lap)
        return parse_plan("# g\n- [ ] step\n") if lap <= 2 else None

    made = []
    res = run_loop(store, "g", StubDoD(flip=99), plan_fn=plan_fn,
                   runner_factory=lambda lap: made.append(lap) or FakeRunner(),
                   autonomy="trusted", max_laps=5)
    # lap1, lap2 run operate (fresh runner each); lap3 plan_fn returns None → stop.
    assert made == [1, 2]                  # one fresh runner per working lap
    assert res.status == "exhausted"


def test_loop_waiting_when_human_needed(store):
    # A force-push trips the inviolable policy wall → operate returns waiting →
    # the loop halts to waiting (the clone never auto-clears a hard rule).
    plan = parse_plan("# g\n- [ ] git push --force origin main\n")
    res = run_loop(store, "g", StubDoD(flip=99), plan=plan,
                   runner_factory=lambda lap: FakeRunner(), autonomy="trusted")
    assert res.status == "waiting" and res.laps == 1


def test_loop_killswitch(store):
    ks = KillSwitch(flag_dir=str(Path(tempfile.mkdtemp())))
    ks.trip()
    plan = parse_plan("# g\n- [ ] step\n")
    res = run_loop(store, "g", StubDoD(flip=99), plan=plan,
                   runner_factory=lambda lap: FakeRunner(), autonomy="trusted",
                   killswitch=ks)
    assert res.status == "killed"


def test_loop_max_laps(store):
    # Fixed plan + never-satisfied DoD → re-runs every lap until the backstop.
    plan = parse_plan("# g\n- [ ] step\n")
    res = run_loop(store, "g", StubDoD(flip=99), plan=plan,
                   runner_factory=lambda lap: FakeRunner(), autonomy="trusted",
                   max_laps=3)
    assert res.status == "max_laps" and res.laps == 3


# ---- write-back (escalation answer → precedent + calibration) ----------------

def test_answer_writes_precedent_and_calibrates(store):
    eid = store.add_escalation(
        1, "regenerate the supabase types after the migration",
        context={"category": "low_confidence",
                 "clone_attempt": {"decision": "skip", "confidence": 0.6}},
        risk=0.3,
    )
    learned = store.learn_from_escalation_answer(eid, "skip")
    assert learned["learned"] is True and learned["decision"] == "skip"
    assert learned["calibrated"] is True            # clone said skip, human said skip → correct
    # The precedent is now retrievable for a similar blocker → autonomy compounds.
    hits = CloneResolver({}, store=store).retrieve("regen supabase types please", "low_confidence")
    assert hits and hits[0]["decision"] == "skip"
    # Calibration recorded a correct event for the category.
    cal = store.get_calibration("low_confidence")
    assert cal["low_confidence"]["correct"] == 1


def test_answer_records_incorrect_when_clone_diverged(store):
    eid = store.add_escalation(
        1, "delete the staging database",
        context={"category": "risk_ceiling",
                 "clone_attempt": {"decision": "approve", "confidence": 0.6}},
        risk=0.8,
    )
    store.learn_from_escalation_answer(eid, "skip")   # human overrides clone's approve
    cal = store.get_calibration("risk_ceiling")
    assert cal["risk_ceiling"]["correct"] == 0 and cal["risk_ceiling"]["total"] == 1


# ---- calibration → thresholds ------------------------------------------------

def test_thresholds_move_with_override_rate(store):
    # High correctness in 'a' → lower bar; low correctness in 'b' → higher bar.
    for _ in range(5):
        store.record_calibration("a", "approve", True, confidence=0.7, source="t")
    for _ in range(5):
        store.record_calibration("b", "approve", False, confidence=0.7, source="t")
    thr = CloneResolver.thresholds_from_calibration(store)
    assert thr["a"] < thr["b"]
    assert thr["a"] < 0.75 < thr["b"] or (thr["a"] <= 0.75 and thr["b"] >= 0.75)


def test_thresholds_ignore_small_samples(store):
    store.record_calibration("c", "approve", True, confidence=0.7, source="t")
    thr = CloneResolver.thresholds_from_calibration(store, min_samples=3)
    assert "c" not in thr            # too few samples → keep the static default
