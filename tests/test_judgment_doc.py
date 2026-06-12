"""Tests for the judgment-doc export — deterministic, no model."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.judgment_doc import build_judgment_doc


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-jdoc", org_id="t", db_path=Path(d) / "m.db")


def test_doc_contains_precedents_and_thresholds(store):
    store.add_precedent("normal", "regenerate the supabase types after a migration",
                        "skip", "I do that by hand later", source="human_answer")
    store.add_precedent("normal", "delete the old logo asset",
                        "approve", "fine, it's unused", source="human_answer")
    for _ in range(4):
        store.record_calibration("normal", "approve", True, confidence=0.7, source="t")

    doc = build_judgment_doc(store, {"practices": ["run tests before commit"]})

    assert "supabase types" in doc
    assert "delete the old logo asset" in doc
    assert "**skip**" in doc and "**approve**" in doc
    assert "Calibrated confidence thresholds" in doc
    assert "run tests before commit" in doc
    assert "Hard rules" in doc  # always present


def test_doc_is_safe_on_empty_brain(store):
    doc = build_judgment_doc(store, {})
    assert "No precedents yet" in doc
    assert "Hard rules" in doc
