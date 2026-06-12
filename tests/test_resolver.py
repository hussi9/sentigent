"""Tests for the CloneResolver — the organ that answers a blocker AS the user.

The LLM path is monkeypatched so tests are deterministic and never hit Ollama.
The retrieval, coercion, and should_apply logic are pure and tested directly.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import resolver as resolver_mod
from sentigent.operator.resolver import (
    APPROVE,
    NEEDS_HUMAN,
    SKIP,
    CloneResolver,
    Resolution,
)

PROFILE = {
    "summary": "ships fast, tests before commit",
    "preferences": ["small PRs"],
    "never_do": ["force-push main"],
}


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-res", org_id="t", db_path=Path(d) / "m.db")


# ---- precedent store + retrieval ---------------------------------------------

def test_precedent_roundtrip_and_retrieval(store):
    store.add_precedent("normal", "regenerate the supabase types after a migration",
                        SKIP, "I do that by hand later", source="human_answer")
    store.add_precedent("normal", "delete the old logo asset",
                        APPROVE, "fine, it's unused", source="human_answer")
    r = CloneResolver(PROFILE, store=store)
    hits = r.retrieve("please regenerate supabase types now", "normal")
    assert hits, "expected a precedent match"
    assert "supabase types" in hits[0]["blocker"]
    assert hits[0]["decision"] == SKIP


def test_retrieve_empty_when_no_store():
    r = CloneResolver(PROFILE, store=None)
    assert r.retrieve("anything", "normal") == []


# ---- should_apply (the apply gate) -------------------------------------------

def test_hard_floor_never_auto_applies():
    # Locked regression: a policy_wall blocker is NEVER clone-resolved, even at conf 1.0.
    res = Resolution(APPROVE, 1.0, "I'd do it", source="llm")
    assert CloneResolver.should_apply(res, policy_wall=True, category="risk_ceiling") is False


def test_confident_approve_applies():
    res = Resolution(APPROVE, 0.95, "yes", source="llm")
    assert CloneResolver.should_apply(res, policy_wall=False, category="normal") is True


def test_confident_skip_applies():
    res = Resolution(SKIP, 0.95, "no", source="llm")
    assert CloneResolver.should_apply(res, policy_wall=False, category="normal") is True


def test_low_confidence_does_not_apply():
    res = Resolution(APPROVE, 0.40, "maybe", source="llm")
    assert CloneResolver.should_apply(res, policy_wall=False, category="normal") is False


def test_needs_human_never_applies():
    res = Resolution(NEEDS_HUMAN, 0.0, "unsure", source="llm")
    assert CloneResolver.should_apply(res, policy_wall=False, category="normal") is False


# ---- resolve() with the LLM mocked -------------------------------------------

def test_resolve_offline_returns_needs_human(monkeypatch):
    monkeypatch.setattr(resolver_mod.local_llm, "llm_available", lambda *a, **k: False)
    r = CloneResolver(PROFILE)
    res = r.resolve({"step_text": "x", "category": "normal"})
    assert res.decision == NEEDS_HUMAN and res.source == "fallback" and res.confidence == 0.0


def test_resolve_clean_approve(monkeypatch):
    monkeypatch.setattr(resolver_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(
        resolver_mod.local_llm, "generate_json",
        lambda *a, **k: {"decision": "approve", "confidence": 0.9,
                         "rationale": "standard for me", "drove": "precedent [1]"},
    )
    r = CloneResolver(PROFILE)
    res = r.resolve({"step_text": "regen types", "category": "normal"}, precedents=[])
    assert res.decision == APPROVE and res.confidence == 0.9 and res.source == "llm"


def test_resolve_malformed_json_returns_needs_human(monkeypatch):
    monkeypatch.setattr(resolver_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod.local_llm, "generate_json", lambda *a, **k: None)
    r = CloneResolver(PROFILE)
    res = r.resolve({"step_text": "x", "category": "normal"}, precedents=[])
    assert res.decision == NEEDS_HUMAN and res.source == "fallback"


def test_coerce_forces_zero_confidence_on_needs_human():
    res = CloneResolver._coerce(
        {"decision": "needs_human", "confidence": 0.9, "rationale": "?"}, []
    )
    assert res is not None and res.decision == NEEDS_HUMAN and res.confidence == 0.0


def test_coerce_rejects_unknown_decision():
    assert CloneResolver._coerce({"decision": "maybe", "confidence": 0.5}, []) is None
