"""Tests for DecisionCapture — the real user-preference signal (Phase 0, A1).

Covers the classifiers (prompt reactions, git reverts), the DecisionCapture
writer against a fake store, the cost token-estimator, and a real store
roundtrip for the decision_events table.
See docs/plans/2026-06-03-operator-autopilot-design.md (A1).
"""
from __future__ import annotations

import os
import tempfile

import pytest

from sentigent.core.decision_capture import (
    DecisionCapture,
    classify_prompt_reaction,
    detect_revert_from_bash,
)
from sentigent.telemetry.cost_tracker import estimate_tokens


# ---- classify_prompt_reaction ----------------------------------------------

@pytest.mark.parametrize("prompt", [
    "no, undo that", "that's wrong", "stop", "revert that change",
    "nope that broke the build", "don't do that",
])
def test_reject_prompts(prompt):
    assert classify_prompt_reaction(prompt) == "reject"


@pytest.mark.parametrize("prompt", [
    "actually use a worktree instead", "rather, do it this way",
    "that should be a neutral label", "redo the migration",
])
def test_correct_prompts(prompt):
    assert classify_prompt_reaction(prompt) == "correct"


@pytest.mark.parametrize("prompt", [
    "perfect, ship it", "lgtm", "looks good", "that works great",
])
def test_approve_prompts(prompt):
    assert classify_prompt_reaction(prompt) == "approve"


@pytest.mark.parametrize("prompt", [
    "add a settings page", "what does this function do?", "",
    "/gstack", "[no-router] just do it", "implement the parser",
])
def test_neutral_prompts_return_none(prompt):
    # New requests / slash-commands / escapes carry no reaction signal.
    assert classify_prompt_reaction(prompt) is None


def test_reject_beats_approve_when_both_present():
    assert classify_prompt_reaction("looks good but undo the last change") == "reject"


# ---- detect_revert_from_bash ------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "git revert HEAD", "git reset --hard origin/main",
    "git checkout -- src/foo.py", "git restore .", "git clean -fd",
])
def test_revert_detected(cmd):
    assert detect_revert_from_bash(cmd) is True


@pytest.mark.parametrize("cmd", [
    "git status", "git add .", "git commit -m 'x'", "ls -la", "", "git log",
])
def test_non_revert_not_detected(cmd):
    assert detect_revert_from_bash(cmd) is False


# ---- DecisionCapture writer (fake store) ------------------------------------

class _FakeStore:
    def __init__(self):
        self.events = []

    def insert_decision_event(self, event):
        self.events.append(event)


def test_capture_prompt_reaction_writes_event():
    store = _FakeStore()
    dc = DecisionCapture(store, agent_id="hussain", org_id="hussain")
    ev = dc.capture_prompt_reaction("no, undo that", prior_trace_id="t-42")
    assert ev is not None
    assert len(store.events) == 1
    assert store.events[0]["kind"] == "reject"
    assert store.events[0]["prior_trace_id"] == "t-42"
    assert store.events[0]["source"] == "prompt_reaction"


def test_capture_prompt_reaction_neutral_writes_nothing():
    store = _FakeStore()
    dc = DecisionCapture(store, agent_id="hussain")
    assert dc.capture_prompt_reaction("add a new endpoint") is None
    assert store.events == []


def test_capture_bash_revert_writes_event():
    store = _FakeStore()
    dc = DecisionCapture(store, agent_id="hussain")
    ev = dc.capture_bash_revert("git reset --hard HEAD~1", prior_trace_id="t-9")
    assert ev is not None and store.events[0]["kind"] == "revert"
    assert store.events[0]["source"] == "bash_revert"
    assert store.events[0]["confidence"] == 0.9


def test_capture_bash_revert_non_revert_writes_nothing():
    store = _FakeStore()
    dc = DecisionCapture(store, agent_id="hussain")
    assert dc.capture_bash_revert("git status") is None
    assert store.events == []


def test_capture_is_fail_soft_on_store_error():
    class _Boom:
        def insert_decision_event(self, event):
            raise RuntimeError("db down")
    dc = DecisionCapture(_Boom(), agent_id="hussain")
    # Must not raise — capturing a signal can never break the session.
    assert dc.capture_prompt_reaction("undo that") is None


# ---- cost token estimator ---------------------------------------------------

def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1          # 4 chars -> 1 token
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens(None) == 0            # type: ignore[arg-type]


# ---- real store roundtrip ---------------------------------------------------

def test_store_decision_events_roundtrip():
    from sentigent.memory.store import MemoryStore

    with tempfile.TemporaryDirectory() as d:
        # MemoryStore takes an explicit db_path; the SENTIGENT_DB_PATH env is NOT
        # honored, so pass db_path directly to keep this test isolated from the
        # real ~/.sentigent DB.
        store = MemoryStore(agent_id="t-agent", org_id="t-org",
                            db_path=os.path.join(d, "t.db"))
        store.insert_decision_event({
            "agent_id": "t-agent", "org_id": "t-org", "ts": 1.0,
            "kind": "reject", "signal": "undo", "source": "prompt_reaction",
            "confidence": 0.7,
        })
        store.insert_decision_event({
            "agent_id": "t-agent", "org_id": "t-org", "ts": 2.0,
            "kind": "revert", "signal": "git reset --hard",
            "source": "bash_revert", "confidence": 0.9,
        })
        rows = store.get_decision_events(limit=10)
        assert len(rows) == 2
        assert rows[0]["ts"] == 2.0  # newest first
        counts = store.get_decision_event_counts()
        assert counts == {"reject": 1, "revert": 1}
        assert store.get_decision_events(kind="revert")[0]["signal"] == "git reset --hard"
