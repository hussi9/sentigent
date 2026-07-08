"""Practice enforcement gate — hold the agent to the user's declared practices.

Closes the 2026-07-07 gap: the practices playbook was declared/counted/benchmarked
but never enforced. Now an active practice whose cadence fires (e.g. git commit)
and wasn't satisfied this session escalates (block) or slows down (warn), per the
user's chosen enforcement level — so they stop re-prompting for tests/review.
"""
from __future__ import annotations

import pytest

from sentigent import Sentigent
from sentigent.core.types import DecisionAction
from sentigent.core.practice_gate import (
    PracticeGate,
    detect_trigger,
    window_since_last_commit,
    _match_kb,
)
from sentigent.memory.store import MemoryStore


# ── trigger detection ────────────────────────────────────────────────────────

def test_detect_trigger_commit():
    assert detect_trigger("git commit -m 'x'") == "commit"
    assert detect_trigger("Bash: git commit -q -m msg") == "commit"


def test_detect_trigger_pr_and_deploy():
    assert detect_trigger("git push origin main") == "pr"
    assert detect_trigger("gh pr create --fill") == "pr"
    assert detect_trigger("vercel --prod") == "deploy"


def test_detect_trigger_none_for_reads():
    assert detect_trigger("git status") is None
    assert detect_trigger("ls -la") is None


# ── KB matching ──────────────────────────────────────────────────────────────

def test_match_kb_maps_declared_text_to_enforceable_practice():
    kb = _match_kb("Run the relevant tests before committing")
    assert kb is not None and kb.key == "tests-before-commit"


def test_match_kb_none_for_prohibition():
    # "Never force-push" is a prohibition — PolicyWall's job, not this gate.
    assert _match_kb("Never force-push a shared branch") is None


# ── window since last commit (correctness: "did you test SINCE last commit") ──

def test_window_stops_at_previous_commit():
    # recent is most-recent-first: a test AFTER the last commit counts.
    recent = ["pytest tests/", "git commit -m prev", "old pytest"]
    assert window_since_last_commit(recent) == ["pytest tests/"]


def test_window_empty_when_commit_is_most_recent():
    # last action was itself a commit → nothing done since → empty window.
    recent = ["git commit -m prev", "pytest tests/"]
    assert window_since_last_commit(recent) == []


def test_window_whole_session_when_no_prior_commit():
    recent = ["pytest tests/", "git add -A", "vim x"]
    assert window_since_last_commit(recent) == recent


# ── gate behavior ────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="t-prac", org_id="t", db_path=str(tmp_path / "m.db"))


def _add(store, text, cadence="commit", enforcement="block"):
    pid = store.add_practice(text, domain="testing", cadence=cadence)
    store.set_practice_enforcement(pid, enforcement)
    return pid


def test_block_practice_escalates_when_unsatisfied(store):
    pid = _add(store, "Run the relevant tests before committing", enforcement="block")
    v = PracticeGate(store).check("Bash", "git commit -m wip", recent_texts=["git status", "ls"])
    assert v is not None
    assert v.action == "escalate"
    assert v.practice_id == pid
    # adherence recorded as skipped
    row = next(p for p in store.get_practices() if p["id"] == pid)
    assert row["times_skipped"] == 1


def test_practice_satisfied_by_recent_test_run(store):
    pid = _add(store, "Run the relevant tests before committing", enforcement="block")
    v = PracticeGate(store).check(
        "Bash", "git commit -m done", recent_texts=["pytest tests/ -q", "git add -A"]
    )
    assert v is None
    row = next(p for p in store.get_practices() if p["id"] == pid)
    assert row["times_followed"] == 1


def test_tests_before_last_commit_do_not_satisfy(store):
    # A pytest run that happened BEFORE the previous commit is stale — committing
    # again must still fire the gate (recent is most-recent-first).
    _add(store, "Run the relevant tests before committing", enforcement="block")
    v = PracticeGate(store).check(
        "Bash", "git commit -m again",
        recent_texts=["git commit -m prev", "pytest tests/ -q"],
    )
    assert v is not None
    assert v.action == "escalate"


def test_warn_level_slows_down_not_escalates(store):
    _add(store, "Run the relevant tests before committing", enforcement="warn")
    v = PracticeGate(store).check("Bash", "git commit -m x", recent_texts=[])
    assert v is not None
    assert v.action == "slow_down"
    assert v.enforcement == "warn"


def test_off_level_never_gates(store):
    _add(store, "Run the relevant tests before committing", enforcement="off")
    assert PracticeGate(store).check("Bash", "git commit -m x", recent_texts=[]) is None


def test_non_commit_action_is_ignored(store):
    _add(store, "Run the relevant tests before committing", enforcement="block")
    assert PracticeGate(store).check("Bash", "git status", recent_texts=[]) is None


def test_block_outranks_warn(store):
    _add(store, "Self-review the full diff before opening a PR", cadence="pr", enforcement="warn")
    _add(store, "Gate merges on a green CI run", cadence="pr", enforcement="block")
    v = PracticeGate(store).check("Bash", "git push origin feature", recent_texts=[])
    assert v is not None and v.enforcement == "block"


# ── store: enforcement dial (the user's "choose what to enforce") ─────────────

def test_enforcement_defaults_to_warn(store):
    pid = store.add_practice("Run the relevant tests before committing", cadence="commit")
    row = next(p for p in store.get_practices() if p["id"] == pid)
    assert row["enforcement"] == "warn"


def test_set_enforcement_rejects_bad_level(store):
    pid = store.add_practice("x", cadence="commit")
    with pytest.raises(ValueError):
        store.set_practice_enforcement(pid, "nuclear")


# ── engine wiring ────────────────────────────────────────────────────────────

def test_evaluate_blocks_commit_without_tests(tmp_db_path):
    judge = Sentigent(profile="default", agent_id="t-prac-eng", db_path=tmp_db_path)
    pid = judge._memory.add_practice(
        "Run the relevant tests before committing", domain="testing", cadence="commit"
    )
    judge._memory.set_practice_enforcement(pid, "block")

    decision = judge.evaluate(
        task="git commit -m 'ship it'",
        context={"tool_name": "Bash", "tool_input": "git commit -m 'ship it'"},
    )
    assert decision.action == DecisionAction.ESCALATE
    assert decision.metadata.get("source") == "practice"
    assert "practice enforced" in decision.reason.lower()


# ── CLI (`sentigent practices …`) ────────────────────────────────────────────

def test_cli_practices_add_enforce_list_roundtrip(tmp_path, capsys):
    from sentigent.cli import _cmd_practices
    db = str(tmp_path / "cli.db")

    _cmd_practices("add", ["Run the relevant tests before committing"], "commit", "t-cli", db)
    _cmd_practices("enforce", ["1", "block"], "commit", "t-cli", db)
    _cmd_practices("list", [], "commit", "t-cli", db)
    out = capsys.readouterr().out
    assert "added #1" in out
    assert "enforcement=block" in out
    assert "block" in out and "Run the relevant tests before committing" in out


def test_cli_practices_enforce_rejects_bad_level(tmp_path, capsys):
    from sentigent.cli import _cmd_practices
    db = str(tmp_path / "cli.db")
    _cmd_practices("add", ["x"], "commit", "t-cli2", db)
    _cmd_practices("enforce", ["1", "nuke"], "commit", "t-cli2", db)
    assert "must be one of" in capsys.readouterr().out


def test_evaluate_allows_commit_after_test_run(tmp_db_path):
    judge = Sentigent(profile="default", agent_id="t-prac-eng2", db_path=tmp_db_path)
    pid = judge._memory.add_practice(
        "Run the relevant tests before committing", domain="testing", cadence="commit"
    )
    judge._memory.set_practice_enforcement(pid, "block")

    # A prior tool call runs the tests → recorded as an episode with that task text.
    judge.evaluate(task="pytest tests/ -q", context={"tool_name": "Bash", "tool_input": "pytest tests/ -q"})
    decision = judge.evaluate(
        task="git commit -m 'ship it'",
        context={"tool_name": "Bash", "tool_input": "git commit -m 'ship it'"},
    )
    assert decision.metadata.get("source") != "practice"
    assert decision.action != DecisionAction.ESCALATE
