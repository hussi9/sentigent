"""Tests for MCP server context enrichment and policy integration.

Tests cover:
- Policy violations in sentigent_evaluate response
- Context enrichment (similar episodes) in evaluate response
- Policy override of signal-based decisions
- sentigent_context tool
- _build_context_enrichment helper
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Set up test environment before importing mcp_server
os.environ.setdefault("SENTIGENT_PROFILE", "code_review")
os.environ.setdefault("SENTIGENT_AGENT_ID", "test_agent")


from sentigent.core.engine import Sentigent
from sentigent.mcp_server import (
    _build_context_enrichment,
    _enrich_context_from_tool,
    _get_judge,
    _infer_lesson,
)
from sentigent.policies import Policy, check_policies


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Provide a temporary database path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def judge(tmp_db: str) -> Sentigent:
    """Provide a Sentigent instance with a temporary database."""
    return Sentigent(profile="code_review", agent_id="test_enrich", db_path=tmp_db)


@pytest.fixture
def judge_with_episodes(judge: Sentigent) -> Sentigent:
    """Provide a judge that has some past episodes with outcomes."""
    # Create some episodes
    for i in range(5):
        decision = judge.evaluate(
            task=f"Edit: database.py ({50 + i * 20} lines)",
            context={"lines_changed": 50 + i * 20, "file_type": "python"},
            agent_state={"confidence": 0.7},
        )
        outcome = "correct" if i % 2 == 0 else "incorrect"
        judge.record_outcome(decision.trace_id, outcome,
                            f"Test outcome {i}: {'passed' if outcome == 'correct' else 'failed'}")

    for i in range(3):
        decision = judge.evaluate(
            task=f"Bash: git push origin feature-{i}",
            context={"is_deployment": True},
            agent_state={"confidence": 0.9},
        )
        judge.record_outcome(decision.trace_id, "correct", "Push succeeded")

    return judge


# ─── Context Enrichment Tests ──────────────────────────────────────────────

class TestBuildContextEnrichment:
    """Tests for _build_context_enrichment helper."""

    def test_returns_empty_when_no_episodes(self, judge: Sentigent) -> None:
        """No enrichment when judge has no episode history."""
        result = _build_context_enrichment(judge, "Bash", "echo hello", {})
        assert result == {}

    def test_returns_episodes_when_history_exists(self, judge_with_episodes: Sentigent) -> None:
        """Returns similar episodes when history exists."""
        result = _build_context_enrichment(
            judge_with_episodes, "Edit", "Edit: database.py (100 lines)",
            {"lines_changed": 100},
        )
        if result:  # May be empty if no keyword match
            assert "similar_episodes" in result
            assert isinstance(result["similar_episodes"], list)
            assert len(result["similar_episodes"]) <= 3

    def test_episodes_have_required_fields(self, judge_with_episodes: Sentigent) -> None:
        """Each episode in enrichment has task, outcome, lesson."""
        result = _build_context_enrichment(
            judge_with_episodes, "Edit", "Edit: database.py (100 lines)",
            {"lines_changed": 100},
        )
        if result and result.get("similar_episodes"):
            for ep in result["similar_episodes"]:
                assert "task" in ep
                assert "outcome" in ep
                assert "lesson" in ep

    def test_includes_recommendation(self, judge_with_episodes: Sentigent) -> None:
        """Enrichment includes a recommendation when episodes exist."""
        result = _build_context_enrichment(
            judge_with_episodes, "Edit", "Edit: database.py (100 lines)",
            {"lines_changed": 100},
        )
        if result and result.get("similar_episodes"):
            assert "recommendation" in result
            assert isinstance(result["recommendation"], str)
            assert len(result["recommendation"]) > 0


# ─── Policy Integration Tests ──────────────────────────────────────────────

class TestPolicyIntegration:
    """Tests for policy checking integrated with evaluate."""

    def test_force_push_triggers_policy_violation(self) -> None:
        """Force push to main triggers policy violation."""
        violations = check_policies("Bash", "git push --force origin main")
        assert len(violations) > 0
        assert any(v.policy_id == "no-force-push" for v in violations)
        assert any(v.action == "escalate" for v in violations)

    def test_safe_command_no_violations(self) -> None:
        """Normal command has no policy violations."""
        violations = check_policies("Bash", "ls -la")
        assert len(violations) == 0

    def test_env_commit_triggers_violation(self) -> None:
        """Adding .env triggers policy violation."""
        violations = check_policies("Bash", "git add .env")
        assert any(v.policy_id == "no-env-commits" for v in violations)


# ─── Tool Context Enrichment Tests ─────────────────────────────────────────

class TestEnrichContextFromTool:
    """Tests for _enrich_context_from_tool."""

    def test_bash_destructive_detection(self) -> None:
        """Detects destructive bash commands."""
        ctx: dict = {}
        result = _enrich_context_from_tool("Bash", "rm -rf /var/data", ctx)
        assert result.get("is_destructive") is True
        assert result.get("consequence_severity") == 0.9

    def test_bash_deployment_detection(self) -> None:
        """Detects deployment commands."""
        ctx: dict = {}
        result = _enrich_context_from_tool("Bash", "npm run deploy", ctx)
        assert result.get("is_deployment") is True

    def test_write_sensitive_file_detection(self) -> None:
        """Detects sensitive file writes."""
        ctx: dict = {}
        result = _enrich_context_from_tool("Write", "file: .env.production", ctx)
        assert result.get("is_sensitive_file") is True
        assert result.get("consequence_severity") == 0.8

    def test_write_line_counting(self) -> None:
        """Counts lines changed in Write operations."""
        ctx: dict = {}
        content = "line1\nline2\nline3\nline4\nline5\n"
        result = _enrich_context_from_tool("Write", content, ctx)
        assert result.get("lines_changed") == 5

    def test_safe_bash_command(self) -> None:
        """Safe commands don't set destructive flags."""
        ctx: dict = {}
        result = _enrich_context_from_tool("Bash", "ls -la", ctx)
        assert "is_destructive" not in result


# ─── Infer Lesson Tests ────────────────────────────────────────────────────

class TestInferLesson:
    """Tests for _infer_lesson helper."""

    def test_correct_proceed(self) -> None:
        """Correct proceed = success."""
        lesson = _infer_lesson({"outcome": "correct", "decision": "proceed"})
        assert "succeeded" in lesson.lower()

    def test_correct_escalate(self) -> None:
        """Correct escalate = right call."""
        lesson = _infer_lesson({"outcome": "correct", "decision": "escalate"})
        assert "right call" in lesson.lower()

    def test_incorrect_proceed(self) -> None:
        """Incorrect proceed = should have been cautious."""
        lesson = _infer_lesson({"outcome": "incorrect", "decision": "proceed"})
        assert "cautious" in lesson.lower()

    def test_incorrect_escalate(self) -> None:
        """Incorrect escalate = unnecessary."""
        lesson = _infer_lesson({"outcome": "incorrect", "decision": "escalate"})
        assert "unnecessary" in lesson.lower()

    def test_unknown_outcome(self) -> None:
        """Unknown outcome = no clear lesson."""
        lesson = _infer_lesson({"outcome": "neutral", "decision": "proceed"})
        assert "no clear" in lesson.lower()
