"""Tests for sentigent hook pre/post behavior."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load sentigent_hook directly from its file path (avoids hyphen-in-dirname issue)
import importlib.util

_hook_path = Path(__file__).parent.parent / "claude-plugin" / "hooks" / "sentigent_hook.py"
_spec = importlib.util.spec_from_file_location("sentigent_hook", _hook_path)
sentigent_hook = importlib.util.module_from_spec(_spec)
sys.modules["sentigent_hook"] = sentigent_hook
_spec.loader.exec_module(sentigent_hook)


def test_save_and_load_trace():
    """_save_trace writes to shared file; _load_trace reads it back."""
    sentigent_hook._save_trace("trace-abc", "Bash", "Bash: echo hello")
    data = sentigent_hook._load_trace()
    assert data is not None
    assert data["trace_id"] == "trace-abc"
    assert data["tool_name"] == "Bash"
    # Cleanup
    sentigent_hook._TRACE_FILE.unlink(missing_ok=True)


def test_load_trace_returns_none_when_no_file():
    """_load_trace returns None gracefully when trace file doesn't exist."""
    sentigent_hook._TRACE_FILE.unlink(missing_ok=True)
    result = sentigent_hook._load_trace()
    assert result is None


def test_pre_hook_approves_safe_tools():
    """pre_hook must approve safe read-only tools without calling judge."""
    for safe in ("Read", "Glob", "Grep", "WebSearch", "LS"):
        result = sentigent_hook.pre_hook(safe, "/some/file.py")
        assert result["decision"] == "approve", f"Expected approve for {safe}"
    # Trace file should NOT exist (safe tools clear it)
    assert not sentigent_hook._TRACE_FILE.exists()


def test_pre_hook_approves_glob():
    """Glob is a safe tool — must be approved without evaluation."""
    result = sentigent_hook.pre_hook("Glob", "**/*.py")
    assert result["decision"] == "approve"


def test_pre_hook_evaluates_bash_and_saves_trace():
    """pre_hook evaluates Bash tool and saves trace_id to file."""
    mock_decision = MagicMock()
    mock_decision.trace_id = "trace-xyz"
    mock_decision.action.value = "proceed"
    mock_decision.judgment_score = 0.9
    mock_decision.reason = "looks fine"

    mock_judge = MagicMock()
    mock_judge.evaluate.return_value = mock_decision

    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        result = sentigent_hook.pre_hook("Bash", "echo hello")

    assert result["decision"] == "approve"
    # Trace file should have been written
    data = sentigent_hook._load_trace()
    assert data is not None
    assert data["trace_id"] == "trace-xyz"
    sentigent_hook._TRACE_FILE.unlink(missing_ok=True)


def test_pre_hook_blocks_on_escalate():
    """pre_hook returns block when judge says escalate."""
    mock_decision = MagicMock()
    mock_decision.trace_id = "trace-esc"
    mock_decision.action.value = "escalate"
    mock_decision.judgment_score = 0.2
    mock_decision.reason = "destructive op"

    mock_judge = MagicMock()
    mock_judge.evaluate.return_value = mock_decision

    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        result = sentigent_hook.pre_hook("Bash", "rm -rf /")

    assert result["decision"] == "block"
    assert "Sentigent" in result.get("reason", "")
    sentigent_hook._TRACE_FILE.unlink(missing_ok=True)


def test_post_hook_records_neutral_on_bash_success():
    """Phase 0 honest-foundation: a Bash command that merely DIDN'T error is not
    a judgment win — it carries no signal about whether the decision was right.
    It must record 'neutral' (excluded from judgment_score), not 'correct'.
    (Previously this asserted 'correct', which is the bug that produced 78k fake
    'correct' rows. See docs/plans/2026-06-03-operator-autopilot-design.md.)"""
    sentigent_hook._save_trace("t-success", "Bash", "Bash: echo hello")

    mock_judge = MagicMock()
    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        result = sentigent_hook.post_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
            "tool_response": "hello",
        })

    assert result["decision"] == "approve"
    mock_judge.record_outcome.assert_called_once()
    call_args = mock_judge.record_outcome.call_args
    assert call_args[0][0] == "t-success"
    assert call_args[0][1] == "neutral"


def test_post_hook_records_incorrect_on_bash_error():
    """post_hook records 'incorrect' when Bash has error."""
    sentigent_hook._save_trace("t-fail", "Bash", "Bash: bad cmd")

    mock_judge = MagicMock()
    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        result = sentigent_hook.post_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "bad cmd"},
            "tool_response": "",
            "error": "command not found",
        })

    assert result["decision"] == "approve"
    mock_judge.record_outcome.assert_called_once()
    call_args = mock_judge.record_outcome.call_args
    assert call_args[0][1] == "incorrect"


def test_post_hook_no_op_without_trace_file():
    """post_hook returns approve silently when no trace file exists."""
    sentigent_hook._TRACE_FILE.unlink(missing_ok=True)

    mock_judge = MagicMock()
    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        result = sentigent_hook.post_hook({
            "tool_name": "Bash",
            "tool_response": "hello",
        })

    assert result["decision"] == "approve"
    mock_judge.record_outcome.assert_not_called()


def test_post_hook_detects_test_pass():
    """post_hook records 'correct' when test runner shows passing."""
    sentigent_hook._save_trace("t-tests", "Bash", "Bash: pytest tests/")

    mock_judge = MagicMock()
    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        sentigent_hook.post_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/"},
            "tool_response": "5 passed in 0.23s",
        })

    call_args = mock_judge.record_outcome.call_args
    assert call_args[0][1] == "correct"
    assert "passed" in call_args[0][2].lower()


def test_post_hook_detects_test_fail():
    """post_hook records 'incorrect' when test runner shows failures."""
    sentigent_hook._save_trace("t-fails", "Bash", "Bash: pytest tests/")

    mock_judge = MagicMock()
    with patch.object(sentigent_hook, "_get_judge", return_value=mock_judge):
        sentigent_hook.post_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/"},
            "tool_response": "3 failed, 2 passed",
        })

    call_args = mock_judge.record_outcome.call_args
    assert call_args[0][1] == "incorrect"
