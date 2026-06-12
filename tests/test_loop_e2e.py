"""End-to-end proof of the Sentigent Loop (spec MVP steps 1-4).

Deterministic: the local model is mocked. Demonstrates the dark-factory will:
  1. A soft blocker the gate would escalate is RESOLVED by the clone → no page.
  2. With the clone unsure (needs_human) → it correctly pages the human.
  3. A hard-floor step is NEVER clone-resolved (pre-flight policy wall).
  4. autonomy_rate reflects clone-resolved / (clone-resolved + asked).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import gate as gate_mod
from sentigent.operator import resolver as resolver_mod
from sentigent.operator.operate import operate
from sentigent.operator.plan import parse_plan
from sentigent.operator.runner import TurnResult


class FakeRunner:
    def drive(self, prompt, *, system="", workdir=None):
        return TurnResult(ok=True, text="did it", input_tokens=10, output_tokens=5, dry_run=True)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(agent_id="t-e2e", org_id="t", db_path=Path(d) / "m.db")
        s.save_operator_profile('{"summary":"ships fast","never_do":["force-push main"]}', source="llm")
        yield s


def _mock_llm(monkeypatch, available=True, resolver_json=None):
    # Gate stays heuristic (our JSON isn't a valid gate verdict → it falls back),
    # so it escalates a low-confidence benign step under 'assisted'. The resolver
    # gets the resolver_json we choose.
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: available)
    monkeypatch.setattr(resolver_mod.local_llm, "llm_available", lambda *a, **k: available)
    monkeypatch.setattr(resolver_mod.local_llm, "generate_json", lambda *a, **k: resolver_json)
    monkeypatch.setattr(gate_mod.local_llm, "generate_json", lambda *a, **k: resolver_json)


def test_clone_resolves_soft_blocker_without_paging(store, monkeypatch):
    _mock_llm(monkeypatch, resolver_json={
        "decision": "approve", "confidence": 0.9,
        "rationale": "this is exactly how I'd do it", "drove": "profile"})
    plan = parse_plan("# g\n- [ ] tidy the README wording\n")
    res = operate(store, plan, autonomy="assisted", runner=FakeRunner(), execute=False)
    # The clone answered the blocker as the user → run completes, nobody paged.
    assert res.status == "done"
    assert res.clone_resolves == 1 and res.asks == 0
    assert res.autonomy_rate == 1.0
    assert res.outcomes[0].clone_resolved is True


def test_clone_pages_human_when_unsure(store, monkeypatch):
    _mock_llm(monkeypatch, resolver_json={
        "decision": "needs_human", "confidence": 0.0,
        "rationale": "I don't actually know your call here"})
    plan = parse_plan("# g\n- [ ] tidy the README wording\n")
    res = operate(store, plan, autonomy="assisted", runner=FakeRunner(), execute=False)
    assert res.status == "waiting"
    assert res.asks == 1 and res.clone_resolves == 0
    assert res.open_escalation_id is not None
    # The clone's attempt is attached to the escalation so the human sees it + it trains.
    esc = store.get_escalations(res.run_id)[0]
    import json as _j
    ctx = _j.loads(esc["context"]) if isinstance(esc["context"], str) else esc["context"]
    assert "clone_attempt" in ctx


def test_hard_floor_never_clone_resolved(store, monkeypatch):
    # Even with the clone eager to approve, a force-push trips the pre-flight policy
    # wall BEFORE the resolver runs — the line stops for the human, always.
    _mock_llm(monkeypatch, resolver_json={
        "decision": "approve", "confidence": 1.0, "rationale": "do it"})
    plan = parse_plan("# g\n- [ ] git push --force origin main\n")
    res = operate(store, plan, autonomy="trusted", runner=FakeRunner(), execute=False)
    assert res.status == "waiting"
    assert res.outcomes[-1].clone_resolved is False
    assert res.outcomes[-1].risk["policy_wall"] is True


def test_compounding_after_writeback(store, monkeypatch):
    # A blocker with NO precedent + clone unsure → pages. The human answers; the
    # answer becomes a precedent. A later similar blocker is retrievable → the
    # substrate for clone-resolution next time exists. (Autonomy compounds.)
    _mock_llm(monkeypatch, resolver_json={"decision": "needs_human", "confidence": 0.0,
                                          "rationale": "unsure"})
    plan = parse_plan("# g\n- [ ] regenerate the supabase types\n")
    res = operate(store, plan, autonomy="assisted", runner=FakeRunner(), execute=False)
    assert res.status == "waiting"
    eid = res.open_escalation_id
    store.answer_escalation(eid, "skip")
    learned = store.learn_from_escalation_answer(eid, "skip")
    assert learned["learned"] is True
    # The precedent now exists and is retrievable for the same class of blocker.
    hits = resolver_mod.CloneResolver({}, store=store).retrieve("regenerate supabase types", "")
    assert hits and hits[0]["decision"] == "skip"
