"""test_learning_loop.py — G2 ProfileLearner + G3 ConfidenceCalibrator.

Locks the compounding loop: the user's escalation answers + reverts feed back
into the per-domain calibration ledger and the operator profile, so each run
needs the user less. Deterministic — the LLM path is forced off.

See docs/plans/2026-06-03-operator-autopilot-design.md (G2, G3).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sentigent.core.confidence_calibrator import (
    ASSISTED,
    AUTOPILOT,
    COPILOT,
    TRUSTED,
    ConfidenceCalibrator,
    DomainCalibration,
)
from sentigent.core.profile_learner import ProfileLearner
from sentigent.intelligence import local_llm
from sentigent.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-learn", org_id="t", db_path=Path(d) / "m.db")


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force every LLM path off so the loop is deterministic."""
    monkeypatch.setattr(local_llm, "llm_available", lambda *a, **k: False)


def _seed_calibration(store, domain, total, correct):
    """Land `total` calibration events for `domain`, `correct` of them correct."""
    for i in range(total):
        store.record_calibration(domain, predicted="continue",
                                 was_correct=(i < correct), source="seed")


# ---------------------------------------------------------------------------
# G3 — ConfidenceCalibrator thresholds
# ---------------------------------------------------------------------------

def test_thin_data_stays_copilot(store):
    # 4 samples (< MIN_SAMPLES) even if all correct => copilot.
    _seed_calibration(store, "frontend", total=4, correct=4)
    cal = ConfidenceCalibrator(store)
    dc = cal.for_domain("frontend")
    assert dc.recommended_autonomy == COPILOT
    assert "thin" in dc.rationale.lower() or "too thin" in dc.rationale.lower()


def test_assisted_band(store):
    # rate 0.7 (>=0.6, <0.8) with n=10 => assisted.
    _seed_calibration(store, "api", total=10, correct=7)
    assert ConfidenceCalibrator(store).for_domain("api").recommended_autonomy == ASSISTED


def test_autopilot_band(store):
    # rate 0.8 with n=10 => autopilot.
    _seed_calibration(store, "frontend", total=10, correct=8)
    assert ConfidenceCalibrator(store).for_domain("frontend").recommended_autonomy == AUTOPILOT


def test_trusted_band(store):
    # rate 0.95 with n=20 => trusted.
    _seed_calibration(store, "frontend", total=20, correct=19)
    assert ConfidenceCalibrator(store).for_domain("frontend").recommended_autonomy == TRUSTED


def test_low_rate_is_copilot(store):
    # rate 0.4 with enough samples => copilot (unreliable).
    _seed_calibration(store, "db", total=10, correct=4)
    assert ConfidenceCalibrator(store).for_domain("db").recommended_autonomy == COPILOT


def test_high_rate_thin_for_trusted_falls_to_autopilot(store):
    # 90%+ but only 10 samples — not enough for trusted, lands autopilot.
    _seed_calibration(store, "frontend", total=10, correct=9)
    assert ConfidenceCalibrator(store).for_domain("frontend").recommended_autonomy == AUTOPILOT


def test_unseen_domain_default(store):
    dc = ConfidenceCalibrator(store).for_domain("never-seen")
    assert dc.recommended_autonomy == COPILOT
    assert dc.total == 0


def test_calibrate_lists_all_and_to_dict(store):
    _seed_calibration(store, "frontend", total=20, correct=19)
    _seed_calibration(store, "db", total=10, correct=4)
    cal = ConfidenceCalibrator(store)
    rows = cal.calibrate()
    assert {r.domain for r in rows} == {"frontend", "db"}
    d = cal.to_dict()
    assert d["frontend"]["recommended_autonomy"] == TRUSTED
    assert d["db"]["recommended_autonomy"] == COPILOT
    assert cal.recommendations()["frontend"] == TRUSTED


def test_calibrate_fail_soft(store):
    class Broken:
        def get_calibration(self, domain=None):
            raise RuntimeError("boom")
    assert ConfidenceCalibrator(Broken()).calibrate() == []
    dc = ConfidenceCalibrator(Broken()).for_domain("x")
    assert isinstance(dc, DomainCalibration)
    assert dc.recommended_autonomy == COPILOT


# ---------------------------------------------------------------------------
# G2 — ProfileLearner
# ---------------------------------------------------------------------------

def _answered_escalation(store, run_id, decision, domain="db"):
    eid = store.add_escalation(run_id, question=f"act on {domain}?",
                               context={"domain": domain}, risk=0.5)
    store.answer_escalation(eid, decision)
    return eid


def test_answered_skip_escalation_becomes_calibration(store):
    plan_id = store.save_plan("goal", source="test")
    run_id = store.start_run(plan_id)
    _answered_escalation(store, run_id, "skip", domain="db")

    res = ProfileLearner(store).learn()
    assert res.calibration_recorded >= 1
    # A 'skip' answer means the ask was valuable => escalate prediction correct.
    calib = store.get_calibration(domain="db")
    assert calib["db"]["total"] >= 1
    assert calib["db"]["correct"] >= 1


def test_plain_approve_escalation_marks_overasking(store):
    plan_id = store.save_plan("goal", source="test")
    run_id = store.start_run(plan_id)
    _answered_escalation(store, run_id, "approve", domain="frontend")

    ProfileLearner(store).learn()
    calib = store.get_calibration(domain="frontend")
    # plain approve => the ask was unnecessary => escalate prediction was wrong.
    assert calib["frontend"]["total"] >= 1
    assert calib["frontend"]["correct"] == 0


def test_reverts_recorded_as_wrong_continue_and_drift(store):
    # Two reverts in 'db' => recorded as wrong 'continue' + a drift signal.
    for _ in range(2):
        store.insert_decision_event({"kind": "revert", "domain": "db",
                                     "signal": "reverted the migration", "ts": 1000.0})
    store.insert_decision_event({"kind": "approve", "domain": "frontend",
                                 "signal": "looks good", "ts": 1001.0})

    res = ProfileLearner(store).learn()
    calib = store.get_calibration()
    assert calib["db"]["total"] == 2
    assert calib["db"]["correct"] == 0          # reverts => continue was wrong
    assert calib["frontend"]["correct"] == 1    # approve => continue was right
    assert any("db" in s for s in res.drift_signals)
    assert res.proposed_practice  # a guarding practice for the reverted domain


def test_writes_new_profile_version_on_strong_signal(store):
    # Seed a low-rate domain so an ask_when rule gets folded in.
    plan_id = store.save_plan("goal", source="test")
    run_id = store.start_run(plan_id)
    _answered_escalation(store, run_id, "skip", domain="db")
    for _ in range(3):
        store.insert_decision_event({"kind": "revert", "domain": "db",
                                     "signal": "bad", "ts": 2000.0})

    res = ProfileLearner(store).learn()
    assert res.profile_version >= 0
    row = store.get_latest_operator_profile()
    assert row is not None and row["source"] == "learned"
    prof = json.loads(row["profile_json"])
    assert "_last_learn_ts" in prof
    assert any("db" in r for r in prof.get("ask_when", []))


def test_idempotent_second_learn_records_nothing_new(store):
    plan_id = store.save_plan("goal", source="test")
    run_id = store.start_run(plan_id)
    _answered_escalation(store, run_id, "skip", domain="db")
    store.insert_decision_event({"kind": "revert", "domain": "db",
                                 "signal": "bad", "ts": 3000.0})

    first = ProfileLearner(store).learn()
    assert first.calibration_recorded >= 2

    second = ProfileLearner(store).learn()
    # Nothing newer than the watermark => no new calibration recorded.
    assert second.calibration_recorded == 0
    assert second.profile_version == -1


def test_autonomy_recommendations_present(store):
    _seed_calibration(store, "frontend", total=20, correct=19)
    res = ProfileLearner(store).learn()
    assert res.autonomy_recommendations.get("frontend") == TRUSTED


def test_learn_never_raises(store):
    class Broken:
        def get_latest_operator_profile(self):
            raise RuntimeError("boom")
    res = ProfileLearner(Broken()).learn()
    # Fail-soft: returns a LearnResult, never throws.
    assert res.profile_version == -1


def test_to_dict_roundtrips(store):
    res = ProfileLearner(store).learn()
    d = res.to_dict()
    assert set(d) == {"calibration_recorded", "drift_signals", "proposed_practice",
                      "autonomy_recommendations", "profile_version"}
