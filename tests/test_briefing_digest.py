"""Tests for the SessionStart RunDigest line in the clone briefing (E3) and the
opt-in inline hook nudge.

Both run on hot paths (SessionStart briefing / PreToolUse hook), so they must be
deterministic, fail-soft, and — for the nudge — OFF unless explicitly opted in.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

from sentigent.core.briefing import build_clone_briefing
from sentigent.memory.store import MemoryStore

# Load the live hook module directly (hyphen in dirname blocks normal import).
_hook_path = Path(__file__).parent.parent / "claude-plugin" / "hooks" / "sentigent_hook.py"
_spec = importlib.util.spec_from_file_location("sentigent_hook", _hook_path)
sentigent_hook = importlib.util.module_from_spec(_spec)
sys.modules["sentigent_hook"] = sentigent_hook
_spec.loader.exec_module(sentigent_hook)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-digest", org_id="t", db_path=Path(d) / "m.db")


def _seed_profile(store: MemoryStore) -> None:
    # A saved profile makes the briefing speak (otherwise it's silent by design).
    store.save_operator_profile(
        '{"summary":"ships fast","preferences":["autonomous"],"source":"llm"}',
        source="llm",
    )


# ── Task 1: RunDigest line ────────────────────────────────────────────────────
def test_briefing_includes_open_escalation_line(store):
    _seed_profile(store)
    eid = store.add_escalation(
        run_id=1, step_id=1,
        question="about to push --force to main; approve?",
        context="{}", risk=0.9,
    )
    text = build_clone_briefing(store)
    assert "Operator waiting on you" in text
    assert f"escalation #{eid}" in text
    assert "operator_answer" in text
    # the question (truncated) is surfaced
    assert "about to push --force" in text


def test_briefing_omits_line_when_no_escalations(store):
    _seed_profile(store)
    text = build_clone_briefing(store)
    assert "Operator waiting on you" not in text


def test_briefing_digest_fail_soft_on_missing_method():
    # A store without get_open_escalations must not break the briefing.
    class NoEsc:
        def get_latest_operator_profile(self):
            return {"summary": "x"}
        def get_practices(self, active_only=True):
            return []
        def get_decision_event_counts(self):
            return {}
        # intentionally no get_open_escalations
    # Should not raise (returns '' or a string, but never blows up).
    out = build_clone_briefing(NoEsc())
    assert isinstance(out, str)


# ── Task 2: inline nudge helper ───────────────────────────────────────────────
def _patch_store(monkeypatch, store: MemoryStore) -> None:
    """Make the hook's MemoryStore(...) return our temp store regardless of args."""
    import sentigent.memory.store as store_mod
    monkeypatch.setattr(store_mod, "MemoryStore", lambda *a, **k: store)


def test_inline_nudge_fires_on_commit_when_opted_in(monkeypatch, store):
    store.add_practice("tests before commit", domain="testing", cadence="commit")
    _patch_store(monkeypatch, store)
    monkeypatch.setenv("SENTIGENT_INLINE_NUDGES", "1")
    out = sentigent_hook._inline_nudge("Bash", "git commit -m 'wip'")
    assert out
    assert "tests before commit" in out
    assert out.startswith("🧬 reminder:")


def test_inline_nudge_silent_on_benign_command(monkeypatch, store):
    store.add_practice("tests before commit", domain="testing", cadence="commit")
    _patch_store(monkeypatch, store)
    monkeypatch.setenv("SENTIGENT_INLINE_NUDGES", "1")
    assert sentigent_hook._inline_nudge("Bash", "ls -la") == ""


def test_inline_nudge_off_by_default(monkeypatch, store):
    store.add_practice("tests before commit", domain="testing", cadence="commit")
    _patch_store(monkeypatch, store)
    monkeypatch.delenv("SENTIGENT_INLINE_NUDGES", raising=False)
    assert sentigent_hook._inline_nudge("Bash", "git commit -m 'wip'") == ""


def test_inline_nudge_no_relevant_practice(monkeypatch, store):
    store.add_practice("deploy on fridays", domain="deploy", cadence="always")
    _patch_store(monkeypatch, store)
    monkeypatch.setenv("SENTIGENT_INLINE_NUDGES", "1")
    # No practice mentions test/review → no nudge.
    assert sentigent_hook._inline_nudge("Bash", "git push origin main") == ""


def test_inline_nudge_never_raises(monkeypatch):
    # If the store blows up, the helper must swallow it and return ''.
    import sentigent.memory.store as store_mod

    def _boom(*a, **k):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(store_mod, "MemoryStore", _boom)
    monkeypatch.setenv("SENTIGENT_INLINE_NUDGES", "1")
    assert sentigent_hook._inline_nudge("Bash", "git commit -m x") == ""
