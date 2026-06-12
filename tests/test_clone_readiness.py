"""Tests for CloneReadiness (the motivation gauge) + the practices store.

Locks the honest contract: the % only climbs as real signal accrues — profile
synthesized, decisions captured, kinds diversified, practices declared. No vanity.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from sentigent.core import clone_readiness
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-clone", org_id="t", db_path=Path(d) / "m.db")


def test_empty_store_is_near_zero(store):
    r = clone_readiness.compute(store)
    assert r.percent <= 5
    assert r.next_action  # always suggests a move
    assert r.stage


def test_synthesized_profile_raises_readiness(store):
    before = clone_readiness.compute(store).percent
    store.save_operator_profile(
        '{"summary":"x","preferences":["a","b"],"coding_standards":["ts"],'
        '"never_do":["delete"],"ask_when":["2fa"],"risk_tolerance":{"deploy":"low"},'
        '"source":"llm"}',
        source="llm",
    )
    after = clone_readiness.compute(store).percent
    assert after > before
    # profile_synthesized + depth should both have earned credit (>= ~35)
    assert after >= 30


def test_practices_raise_readiness(store):
    before = clone_readiness.compute(store).percent
    store.add_practice("tests before commit", domain="testing", cadence="commit")
    store.add_practice("review diff before PR", domain="review", cadence="pr")
    after = clone_readiness.compute(store).percent
    assert after > before


def test_decision_signal_raises_volume_and_diversity(store):
    before = clone_readiness.compute(store)
    now = time.time()
    for kind in ("approve", "reject", "correct", "revert"):
        for _ in range(5):
            store.insert_decision_event({
                "ts": now, "kind": kind, "domain": "global",
                "signal": "x", "target": "y", "source": "test",
            })
    after = clone_readiness.compute(store)
    assert after.percent > before.percent
    diversity = next(c for c in after.components if c.key == "signal_diversity")
    assert diversity.pct == 1.0  # all 4 kinds present


def test_readiness_never_exceeds_100(store):
    store.save_operator_profile(
        '{"summary":"x","preferences":["a"],"coding_standards":["b"],'
        '"never_do":["c"],"ask_when":["d"],"risk_tolerance":{"x":"low"},"source":"llm"}',
        source="llm",
    )
    now = time.time()
    for kind in ("approve", "reject", "correct", "revert"):
        for _ in range(100):
            store.insert_decision_event({
                "ts": now, "kind": kind, "domain": "global",
                "signal": "x", "target": "y", "source": "test",
            })
    for i in range(12):
        store.add_practice(f"practice {i}")
    assert clone_readiness.compute(store).percent <= 100


# ---- practices store roundtrip + adherence ------------------------------------

def test_practices_roundtrip_and_adherence(store):
    pid = store.add_practice("Run full suite before milestone", domain="testing", cadence="milestone")
    rows = store.get_practices()
    assert len(rows) == 1
    assert rows[0]["text"] == "Run full suite before milestone"
    assert rows[0]["cadence"] == "milestone"

    store.record_practice_adherence(pid, followed=True)
    store.record_practice_adherence(pid, followed=True)
    store.record_practice_adherence(pid, followed=False)
    rows = store.get_practices()
    assert rows[0]["times_followed"] == 2
    assert rows[0]["times_skipped"] == 1

    store.set_practice_active(pid, False)
    assert store.get_practices(active_only=True) == []
    assert len(store.get_practices(active_only=False)) == 1
