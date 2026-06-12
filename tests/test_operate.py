"""Tests for OperatorRunner stream parsing + the operate() control loop.

The loop runs in dry-run with a fake runner and the gate forced offline
(heuristic), so it's deterministic and never spawns claude or the LLM.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import gate as gate_mod
from sentigent.operator import operate as operate_mod
from sentigent.operator.operate import operate
from sentigent.operator.plan import parse_plan
from sentigent.operator.runner import OperatorRunner, TurnResult, parse_stream_json
from sentigent.operator.safety import KillSwitch


# ---- OperatorRunner / OutputObserver ------------------------------------------

def test_parse_stream_json_extracts_text_tools_usage():
    raw = (
        '{"type":"assistant","message":{"content":['
        '{"type":"text","text":"working"},'
        '{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}],'
        '"usage":{"input_tokens":100,"output_tokens":20}}}\n'
        '{"type":"result","result":"done","usage":{"input_tokens":120,"output_tokens":25}}\n'
    )
    r = parse_stream_json(raw)
    assert r.ok
    assert r.text == "done"               # result text wins over streamed text
    assert len(r.tool_uses) == 1
    assert r.tool_uses[0]["name"] == "Bash"
    assert "ls -la" in r.tool_uses[0]["input_summary"]
    assert r.input_tokens == 120 and r.output_tokens == 25


def test_parse_stream_json_tolerates_garbage():
    r = parse_stream_json("not json\n{bad\n")
    assert r.ok is False


def test_runner_dry_run_is_synthetic():
    t = OperatorRunner(dry_run=True).drive("add a hook", system="be me")
    assert t.ok and t.dry_run
    assert "add a hook" in t.text
    assert t.tool_uses == []


# ---- operate() loop -----------------------------------------------------------

class FakeRunner:
    def __init__(self, in_tok=10, out_tok=5):
        self.in_tok, self.out_tok = in_tok, out_tok
        self.calls = 0

    def drive(self, prompt, *, system="", workdir=None):
        self.calls += 1
        return TurnResult(ok=True, text="did it", input_tokens=self.in_tok,
                          output_tokens=self.out_tok, dry_run=True)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(agent_id="t-op", org_id="t", db_path=Path(d) / "m.db")
        s.save_operator_profile('{"summary":"ships fast","source":"llm"}', source="llm")
        yield s


@pytest.fixture(autouse=True)
def _offline_gate(monkeypatch):
    # Force the ProfileGate onto its deterministic heuristic (no Ollama in tests).
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)


def test_happy_path_all_steps_done(store):
    plan = parse_plan("# demo\n- [ ] add a useTheme hook\n- [ ] build the toggle component\n")
    fake = FakeRunner()
    res = operate(store, plan, autonomy="trusted", runner=fake, execute=False)
    assert res.status == "done"
    assert res.steps_done == 2
    assert fake.calls == 2
    # the run + audit events were persisted
    events = store.get_run_events(res.run_id)
    types = {e["type"] for e in events}
    assert "run_started" in types and "step_done" in types and "run_ended" in types
    assert res.spent_usd > 0


def test_policy_wall_step_pauses_run_for_escalation(store):
    plan = parse_plan(
        "# demo\n- [ ] add a hook\n- [ ] git push --force origin main\n- [ ] deploy\n"
    )
    # 'trusted' won't ask on the offline-heuristic's low confidence, so the benign
    # step proceeds and the force-push is what trips the inviolable policy wall.
    res = operate(store, plan, autonomy="trusted", runner=FakeRunner(), execute=False)
    assert res.status == "waiting"
    assert res.open_escalation_id is not None
    asked = [o for o in res.outcomes if o.asked]
    assert asked and asked[-1].risk["policy_wall"] is True
    # the open escalation is queryable (the in-session answer surface)
    assert len(store.get_open_escalations(res.run_id)) == 1


def test_killswitch_stops_run(store):
    ks = KillSwitch(flag_dir=str(Path(tempfile.mkdtemp())))
    ks.trip()  # global
    plan = parse_plan("# demo\n- [ ] add a hook\n")
    res = operate(store, plan, autonomy="trusted", runner=FakeRunner(), killswitch=ks, execute=False)
    assert res.status == "killed"
    assert res.outcomes[0].status == "killed"


def test_budget_exhaustion_stops_run(store):
    plan = parse_plan("# demo\n- [ ] step one\n- [ ] step two\n")
    # tiny budget + big tokens → exceeded on the first step
    res = operate(store, plan, autonomy="trusted", runner=FakeRunner(in_tok=10_000, out_tok=10_000),
                  budget_usd=0.0000001, execute=False)
    assert res.status == "budget_exhausted"
    assert res.outcomes[-1].status == "budget"


def test_run_result_digest_renders(store):
    plan = parse_plan("# demo\n- [ ] add a hook\n")
    res = operate(store, plan, autonomy="trusted", runner=FakeRunner(), execute=False)
    d = res.digest()
    assert "Operator run" in d and "steps done" in d
