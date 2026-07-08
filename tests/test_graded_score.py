"""Graded vs observed outcome split — the honest-metrics regression guard.

The 2026-07-07 principal review found judgment_score was dominated by legacy
auto-recorded rows whose feedback is literally "Bash command succeeded" —
they measure tool exit codes, not judgment quality. Graded counts must
exclude them; the default (observed) counts keep their historical meaning.
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from sentigent.memory.store import AUTO_FEEDBACK_EXACT, MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="t-graded", org_id="t", db_path=str(tmp_path / "m.db"))


def _episode(store: MemoryStore, outcome: str, feedback: str | None) -> None:
    conn = sqlite3.connect(store.db_path)
    try:
        conn.execute(
            """
            INSERT INTO episodes
                (trace_id, agent_id, org_id, timestamp, task, context,
                 agent_state, signals, decision, reason, outcome, outcome_feedback)
            VALUES (?, ?, ?, '2026-07-07T00:00:00+00:00', 'x', '{}',
                    '{}', '{}', 'proceed', '', ?, ?)
            """,
            (str(uuid.uuid4()), store.agent_id, store.org_id, outcome, feedback),
        )
        conn.commit()
    finally:
        conn.close()


def test_graded_counts_exclude_auto_feedback(store):
    _episode(store, "correct", "Bash command succeeded")   # auto — excluded
    _episode(store, "correct", "Edit succeeded")            # auto — excluded
    _episode(store, "correct", None)                        # explicit, no note — graded
    _episode(store, "incorrect", "user rejected the diff")  # human — graded

    total_all, correct_all = store.get_outcome_counts()
    assert (total_all, correct_all) == (4, 3)

    total_graded, correct_graded = store.get_outcome_counts(graded_only=True)
    assert (total_graded, correct_graded) == (2, 1)


def test_graded_counts_exclude_neutral_and_are_case_insensitive(store):
    _episode(store, "neutral", None)                        # neutral — never graded
    _episode(store, "correct", "  Bash Command Succeeded ") # auto (case/space) — excluded
    _episode(store, "correct", "approved in review")        # human — graded

    total_graded, correct_graded = store.get_outcome_counts(graded_only=True)
    assert (total_graded, correct_graded) == (1, 1)


def test_exact_match_does_not_over_exclude_human_notes(store):
    # Human notes that merely MENTION auto vocabulary must still count as graded
    # — this is the over-exclusion bug the exact-match fix closes.
    _episode(store, "correct", "good, it caught the wrong exit code before shipping")
    _episode(store, "correct", "Deploy succeeded — hardened version live on prod")
    _episode(store, "incorrect", "Bash failed: command not found (exit code 127)")

    total_graded, correct_graded = store.get_outcome_counts(graded_only=True)
    assert (total_graded, correct_graded) == (3, 2)


def test_tool_completed_is_excluded(store):
    # 'Tool completed' is a legacy auto string too — it must NOT count as graded
    # (the substring approach missed it; exact-match catches it).
    _episode(store, "correct", "Tool completed")
    _episode(store, "correct", "genuinely correct call")
    total_graded, correct_graded = store.get_outcome_counts(graded_only=True)
    assert (total_graded, correct_graded) == (1, 1)


def test_auto_exact_strings_are_lowercase():
    # The SQL match lowercases+trims feedback; the set must be lowercase to match.
    assert all(s == s.lower().strip() for s in AUTO_FEEDBACK_EXACT)


def test_engine_graded_judgment_score(tmp_judge):
    d1 = tmp_judge.evaluate(task="edit config", context={"tool_name": "Edit"})
    tmp_judge.record_outcome(d1.trace_id, "correct", "Edit succeeded")
    d2 = tmp_judge.evaluate(task="deploy", context={"tool_name": "Bash"})
    tmp_judge.record_outcome(d2.trace_id, "incorrect", "user reverted this")

    # Observed score counts both; graded score sees only the human-graded row.
    assert tmp_judge.judgment_score == pytest.approx(0.5)
    assert tmp_judge.graded_judgment_score == pytest.approx(0.0)
