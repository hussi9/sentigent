"""Tests for the learned steering-file export — deterministic, no model."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.steering_doc import build_steering_doc


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-steer", org_id="t", db_path=Path(d) / "m.db")


def test_steering_contains_rules_standards_and_decisions(store):
    store.add_precedent("normal", "regenerate the supabase types after a migration",
                        "skip", "I do that by hand later", source="human_answer")
    for _ in range(4):
        store.record_calibration("normal", "approve", True, confidence=0.7, source="t")

    profile = {
        "summary": "Senior engineer who ships autonomously.",
        "coding_standards": ["Use TypeScript", "Follow Prettier"],
        "never_do": ["Never pause between tasks"],
        "preferences": ["Autonomous execution"],
        "ask_when": ["A true hard blocker that can't be resolved programmatically"],
        "risk_tolerance": {"deploy": "low", "frontend": "high"},
        "practices": [{"text": "Run the full test suite before a milestone commit", "cadence": "always"}],
    }
    doc = build_steering_doc(store, profile, project="myrepo")

    # Standard steering format + provenance framing.
    assert doc.startswith("# AGENTS.md")
    assert "learned" in doc.lower()
    # Hard rules section is present and first-class.
    assert "Hard rules" in doc
    assert "Never pause between tasks" in doc  # profile never_do merged in
    # Conventions, practices, preferences, ask-when, risk posture all render.
    assert "Use TypeScript" in doc
    assert "Run the full test suite before a milestone commit" in doc
    assert "Autonomous execution" in doc
    assert "hard blocker" in doc
    assert "deploy" in doc and "frontend" in doc
    # Learned decision default shows through.
    assert "supabase types" in doc and "**skip**" in doc
    # Calibrated autonomy table rendered from outcomes.
    assert "Calibrated autonomy" in doc
    # Provenance footer names the project.
    assert "myrepo" in doc


def test_steering_is_safe_on_empty_brain(store):
    doc = build_steering_doc(store, {})
    # Never raises, still emits a valid steering file with the inviolable rules.
    assert doc.startswith("# AGENTS.md")
    assert "Hard rules" in doc
    assert "No precedents recorded yet" in doc
