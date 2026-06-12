"""Tests for ProfileReview (Step 2) + the best-practices KB.

Deterministic backbone is always tested; the LLM enrichment path is mocked.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.core import profile_review
from sentigent.core import profile_review as pr_mod
from sentigent.intelligence import local_llm
from sentigent.memory.store import MemoryStore
from sentigent.operator import best_practices as bp


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-review", org_id="t", db_path=Path(d) / "m.db")


# ---- best-practices KB --------------------------------------------------------

def test_kb_has_high_importance_practices():
    kb = bp.UNIVERSAL
    assert len(kb) >= 12
    assert any(p.importance == "high" for p in kb)
    # every practice has keywords for coverage detection
    assert all(p.keywords for p in kb)


def test_practice_coverage_match():
    p = bp.Practice("x", "testing", "run tests", "", "high", "commit", ["test", "suite"])
    assert p.covered_by("Run the full test suite before commit") is True
    assert p.covered_by("deploy to production") is False


# ---- review backbone ----------------------------------------------------------

def test_empty_profile_is_all_gaps(monkeypatch, store):
    monkeypatch.setattr(pr_mod.local_llm, "llm_available", lambda *a, **k: False)
    r = profile_review.review(store)
    assert r.coverage_pct == 0
    assert len(r.gaps) == len(bp.UNIVERSAL)   # nothing covered yet
    assert r.good == []
    # gaps sorted high-importance first
    assert r.gaps[0].importance == "high"


def test_practices_become_good_and_raise_coverage(monkeypatch, store):
    monkeypatch.setattr(pr_mod.local_llm, "llm_available", lambda *a, **k: False)
    store.add_practice("Run the full test suite before commit", domain="testing", cadence="commit")
    store.add_practice("Self-review the diff before opening a PR", domain="review", cadence="pr")
    r = profile_review.review(store)
    assert r.coverage_pct > 0
    good_texts = " ".join(i.text for i in r.good).lower()
    assert "test" in good_texts or "review" in good_texts
    # those two practices are no longer gaps
    gap_keys = {g.key for g in r.gaps}
    assert "tests-before-commit" not in gap_keys
    assert "self-review-diff" not in gap_keys


def test_profile_traits_cover_practices(monkeypatch, store):
    monkeypatch.setattr(pr_mod.local_llm, "llm_available", lambda *a, **k: False)
    store.save_operator_profile(
        '{"summary":"careful","never_do":["never force-push main"],'
        '"coding_standards":["never commit a secret","validate input with zod"],"source":"llm"}',
        source="llm",
    )
    r = profile_review.review(store)
    gap_keys = {g.key for g in r.gaps}
    assert "no-force-push-shared" not in gap_keys
    assert "no-secrets-in-code" not in gap_keys


def test_llm_enriches_good_and_bad(monkeypatch, store):
    monkeypatch.setattr(pr_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(pr_mod.local_llm, "generate_json", lambda *a, **k: {
        "good": [{"text": "Ships fast and autonomously", "why": "high throughput"}],
        "bad": [{"text": "Never pauses to confirm", "why": "risky on destructive actions"}],
    })
    store.save_operator_profile('{"summary":"always execute, never pause","source":"llm"}', source="llm")
    r = profile_review.review(store)
    assert r.source == "llm"
    assert any("autonom" in i.text.lower() for i in r.good)
    assert any("pause" in i.text.lower() for i in r.bad)


def test_review_never_raises_on_broken_store():
    class Broken:
        def get_latest_operator_profile(self): raise RuntimeError("x")
        def get_practices(self, active_only=True): raise RuntimeError("x")
    r = profile_review.review(Broken())   # must not raise
    assert isinstance(r.gaps, list)
    assert r.coverage_pct == 0
