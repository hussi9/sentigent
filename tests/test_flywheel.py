"""Tests for the Flywheel phase engine (run_flywheel). Deterministic: offline gate,
fake runner, stub DoDs, trusted autonomy — never spawns claude or Ollama.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import gate as gate_mod
from sentigent.operator.flywheel import (
    ADVANCE,
    ESCALATE,
    LOOPBACK,
    Phase,
    run_flywheel,
)
from sentigent.operator.plan import parse_plan
from sentigent.operator.runner import TurnResult
from sentigent.operator.safety import KillSwitch


class FakeRunner:
    def drive(self, prompt, *, system="", workdir=None):
        return TurnResult(ok=True, text="did it", input_tokens=10, output_tokens=5, dry_run=True)


class StubDoD:
    def __init__(self, flip=1):
        self.calls = 0
        self.flip = flip

    def satisfied(self, repo_path):
        self.calls += 1
        ok = self.calls >= self.flip
        return type("R", (), {"satisfied": ok, "reason": "stub" if ok else "not yet"})()


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(agent_id="t-fly", org_id="t", db_path=Path(d) / "m.db")
        s.save_operator_profile('{"summary":"ships fast"}', source="llm")
        yield s


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)


@pytest.fixture
def ks():
    # Isolated kill switch so tests never collide with real ~/.sentigent run flags.
    with tempfile.TemporaryDirectory() as d:
        yield KillSwitch(flag_dir=d)


def _phase(name, **kw):
    return Phase(name=name, goal=f"do {name}",
                 plan=parse_plan(f"# {name}\n- [ ] work on {name}\n"),
                 dod=StubDoD(flip=1), autonomy="trusted", **kw)


def test_flywheel_completes_through_phases(store, ks):
    phases = [_phase("research"), _phase("plan"), _phase("implement")]
    res = run_flywheel(store, phases, runner_factory=lambda lap: FakeRunner(), killswitch=ks)
    assert res.status == "completed"
    assert [h.name for h in res.history] == ["research", "plan", "implement"]
    assert all(h.decision == ADVANCE for h in res.history)


def test_flywheel_escalates_on_hard_rule(store, ks):
    # A force-push phase trips the policy wall → loop waiting → flywheel escalates.
    danger = Phase(name="deploy", goal="deploy",
                   plan=parse_plan("# deploy\n- [ ] git push --force origin main\n"),
                   dod=StubDoD(flip=1), autonomy="trusted")
    res = run_flywheel(store, [_phase("plan"), danger], runner_factory=lambda lap: FakeRunner(), killswitch=ks)
    assert res.status == "escalated"
    assert res.history[-1].name == "deploy" and res.history[-1].decision == ESCALATE


def test_flywheel_loopback_to_target(store, ks):
    # Steering rejects the plan ONCE (NO-GO → loopback to brainstorm), then passes.
    state = {"n": 0}

    def steering_gate(loop_res):
        state["n"] += 1
        return (LOOPBACK, "NO-GO: refine") if state["n"] == 1 else (ADVANCE, "GO")

    phases = [
        _phase("brainstorm"),
        _phase("steering", gate=steering_gate, loopback_to="brainstorm"),
        _phase("plan"),
    ]
    res = run_flywheel(store, phases, runner_factory=lambda lap: FakeRunner(), killswitch=ks)
    assert res.status == "completed"
    names = [h.name for h in res.history]
    # brainstorm, steering(NO-GO→loopback), brainstorm again, steering(GO), plan
    assert names == ["brainstorm", "steering", "brainstorm", "steering", "plan"]
    assert res.history[1].decision == LOOPBACK


def test_flywheel_max_cycles_backstop(store, ks):
    # A phase whose DoD is never satisfied loops back forever → bounded by max_cycles.
    stuck = Phase(name="impl", goal="impl",
                  plan=parse_plan("# impl\n- [ ] work\n"),
                  dod=StubDoD(flip=99), autonomy="trusted", loopback_to="impl")
    res = run_flywheel(store, [stuck], runner_factory=lambda lap: FakeRunner(),
                       killswitch=ks, max_cycles=3, max_laps=2)
    assert res.status == "max_cycles" and res.cycles == 3


def test_flywheel_digest_renders(store, ks):
    res = run_flywheel(store, [_phase("research")], runner_factory=lambda lap: FakeRunner(), killswitch=ks)
    d = res.digest()
    assert "Flywheel" in d and "research" in d
