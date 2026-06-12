"""Tests for the Operator judgment core — risk, plan, gate, escalation, preview.

The gate's LLM path is always mocked; these lock the deterministic behavior that
makes the dry-run trustworthy (risk floor, escalation logic, plan parsing).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.operator import risk as risk_mod
from sentigent.operator.escalation import (
    EscalationDecider, ASSISTED, COPILOT, AUTOPILOT, TRUSTED,
)
from sentigent.operator.gate import ProfileGate, Verdict, CONTINUE, CORRECT, ESCALATE
from sentigent.operator.plan import parse_plan
from sentigent.operator.preview import preview_plan
from sentigent.operator import gate as gate_mod
from sentigent.intelligence import local_llm
from sentigent.memory.store import MemoryStore


# ---- RiskAssessor / PolicyWall -------------------------------------------------

def test_force_push_main_is_policy_wall():
    r = risk_mod.RiskAssessor().assess("git push --force origin main")
    assert r.policy_wall is True
    assert r.category == "force_push"
    assert r.level == "critical"


def test_prod_db_and_delete_flagged():
    a = risk_mod.RiskAssessor()
    assert a.assess("supabase db push").policy_wall is True
    assert a.assess("rm -rf build/").policy_wall is True
    assert a.assess("send the launch email to the beta list").category == "external_send"


def test_routine_change_is_low_risk():
    r = risk_mod.RiskAssessor().assess("add a useTheme hook")
    assert r.policy_wall is False
    assert r.level == "low"


# ---- PlanIngest ----------------------------------------------------------------

def test_parse_checkbox_plan_with_heading_and_done_state():
    text = (
        "# Ship feature\n"
        "- [ ] do the thing\n"
        "- [x] already done\n"
        "- [ ] run the test suite\n"
    )
    plan = parse_plan(text)
    assert plan.goal == "Ship feature"
    assert len(plan.steps) == 3
    assert len(plan.pending) == 2          # the [x] is excluded
    assert plan.steps[2].domain == "test"  # inferred


def test_parse_numbered_and_bullets():
    plan = parse_plan("1. first\n2. second\n- third")
    assert len(plan.steps) == 3


# ---- ProfileGate ---------------------------------------------------------------

def test_gate_coerces_valid_llm_json(monkeypatch):
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(gate_mod.local_llm, "generate_json", lambda *a, **k: {
        "decision": "correct", "confidence": 0.8,
        "reason": "I'd add the test first.", "matched_rules": ["tests before commit"],
        "correction": "write the test, then commit",
    })
    g = ProfileGate({"summary": "x"}, practices=[])
    v = g.judge("commit the changes")
    assert v.decision == CORRECT
    assert v.confidence == 0.8
    assert v.correction


def test_gate_falls_back_to_heuristic_when_offline(monkeypatch):
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)
    g = ProfileGate({"summary": "x"}, practices=[{"text": "always run tests"}])
    v = g.judge("run the test suite")
    assert v.source == "heuristic"
    assert v.decision == CONTINUE


def test_gate_rejects_garbage_llm_then_heuristic(monkeypatch):
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(gate_mod.local_llm, "generate_json", lambda *a, **k: {"bad": "shape"})
    g = ProfileGate({"summary": "x"}, practices=[])
    v = g.judge("do something")
    assert v.source == "heuristic"


# ---- EscalationDecider ---------------------------------------------------------

def _v(decision=CONTINUE, conf=0.9, corr=""):
    return Verdict(decision=decision, confidence=conf, reason="r", correction=corr)


def test_policy_wall_always_asks_even_trusted():
    risk = risk_mod.RiskScore(0.95, "force_push", ["force-push"], policy_wall=True)
    d = EscalationDecider(TRUSTED).decide("git push --force", _v(), risk)
    assert d.ask is True
    assert d.trigger == "policy_wall"


def test_copilot_asks_everything():
    risk = risk_mod.RiskScore(0.05, "normal", [])
    d = EscalationDecider(COPILOT).decide("trivial", _v(), risk)
    assert d.ask is True


def test_assisted_auto_proceeds_low_risk_confident():
    risk = risk_mod.RiskScore(0.05, "normal", [])
    d = EscalationDecider(ASSISTED).decide("add a hook", _v(conf=0.9), risk)
    assert d.ask is False


def test_assisted_asks_on_low_confidence():
    risk = risk_mod.RiskScore(0.05, "normal", [])
    d = EscalationDecider(ASSISTED).decide("murky step", _v(conf=0.3), risk)
    assert d.ask is True
    assert d.trigger == "low_confidence"


def test_escalate_verdict_asks():
    risk = risk_mod.RiskScore(0.05, "normal", [])
    d = EscalationDecider(AUTOPILOT).decide("weird", _v(decision=ESCALATE), risk)
    assert d.ask is True


def test_high_risk_correct_still_hits_risk_ceiling():
    # Regression: a CORRECT verdict on a risky deploy must NOT bypass the risk
    # ceiling (the correction doesn't lower the blast radius).
    risk = risk_mod.RiskScore(0.7, "deploy", ["production deploy"])
    d = EscalationDecider(AUTOPILOT).decide(
        "deploy with vercel --prod", _v(decision=CORRECT, conf=0.8, corr="use skill-router"), risk
    )
    assert d.ask is True
    assert d.trigger == "risk_ceiling"


def test_low_risk_correct_auto_applies():
    risk = risk_mod.RiskScore(0.05, "normal", [])
    d = EscalationDecider(AUTOPILOT).decide(
        "commit", _v(decision=CORRECT, conf=0.9, corr="add the test first"), risk
    )
    assert d.ask is False
    assert d.trigger == "auto-correct"


# ---- preview_plan end-to-end (LLM offline → heuristic) -------------------------

@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-op", org_id="t", db_path=Path(d) / "m.db")


def test_preview_plan_flags_dangerous_steps(monkeypatch, store):
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)
    store.save_operator_profile('{"summary":"ships fast","source":"llm"}', source="llm")
    plan = parse_plan(
        "# demo\n- [ ] add a hook\n- [ ] git push --force origin main\n- [ ] deploy with vercel --prod\n"
    )
    res = preview_plan(store, plan, autonomy="autopilot")
    assert len(res.reviews) == 3
    # the force-push must be a policy-wall ask regardless of autonomy
    fp = res.reviews[1]
    assert fp.risk.policy_wall is True
    assert fp.escalation.ask is True
    # readiness present and is a dict
    assert "percent" in res.readiness
    assert res.asks >= 1
