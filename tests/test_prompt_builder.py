"""Tests for the active prompt builder."""
from __future__ import annotations

import pytest

from sentigent.core.prompt_builder import (
    abandon_session,
    answer_field,
    assess_prompt_quality,
    get_session_status,
    list_templates,
    skip_field,
    start_session,
)


# ── list_templates ──────────────────────────────────────────────────────────────

class TestListTemplates:
    def test_returns_all_templates(self):
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "product_spec" in names
        assert "pr_review" in names
        assert "bug_report" in names
        assert "code_refactor" in names
        assert "architecture_decision" in names
        assert "api_design" in names
        assert "task_breakdown" in names

    def test_each_has_required_fields(self):
        for t in list_templates():
            assert "name" in t
            assert "description" in t
            assert t["fields"] > 0
            assert t["required_fields"] > 0

    def test_at_least_seven_templates(self):
        assert len(list_templates()) >= 7

    def test_each_template_has_skill(self):
        for t in list_templates():
            assert "skill" in t, f"Template {t['name']} missing 'skill'"
            assert t["skill"], f"Template {t['name']} has empty skill"

    def test_skill_mappings_are_correct(self):
        by_name = {t["name"]: t["skill"] for t in list_templates()}
        assert by_name["bug_report"] == "debug"
        assert by_name["code_refactor"] == "refactor"
        assert by_name["pr_review"] == "code-review:code-review"
        assert by_name["product_spec"] == "feature-dev:feature-dev"
        assert by_name["architecture_decision"] == "docs"


# ── start_session ───────────────────────────────────────────────────────────────

class TestStartSession:
    def test_returns_session_id(self):
        result = start_session("product_spec")
        assert "session_id" in result
        assert len(result["session_id"]) == 12

    def test_returns_first_question(self):
        result = start_session("product_spec")
        assert result["status"] == "in_progress"
        assert result["field"] == "name"
        assert "?" in result["question"]

    def test_progress_shows_one_of_total(self):
        result = start_session("product_spec")
        assert result["progress"].startswith("1/")

    def test_invalid_template_returns_error(self):
        result = start_session("does_not_exist")
        assert "error" in result

    def test_all_templates_start_cleanly(self):
        for t in list_templates():
            result = start_session(t["name"])
            assert "session_id" in result, f"Template {t['name']} failed to start"
            assert result["status"] == "in_progress"


# ── answer_field ────────────────────────────────────────────────────────────────

class TestAnswerField:
    def _start(self, template: str = "product_spec") -> str:
        return start_session(template)["session_id"]

    def test_advances_to_next_question(self):
        sid = self._start()
        result = answer_field(sid, "My login feature")
        assert result["status"] == "in_progress"
        assert result["answered"] == "name"
        assert result["field"] == "problem"

    def test_required_blank_answer_rejected(self):
        sid = self._start()
        result = answer_field(sid, "")
        assert result["status"] == "needs_answer"
        assert "required" in result["error"]

    def test_required_whitespace_only_rejected(self):
        sid = self._start()
        result = answer_field(sid, "   ")
        assert result["status"] == "needs_answer"

    def test_progress_increments(self):
        sid = self._start()
        result = answer_field(sid, "Feature name")
        assert result["progress"].startswith("2/")

    def test_expired_session_returns_error(self):
        result = answer_field("nonexistent123", "answer")
        assert "error" in result

    def test_complete_all_fields_returns_prompt(self):
        """Walk through a full product_spec session."""
        sid = self._start("bug_report")
        answers = [
            "Login fails on Firefox",               # summary
            "1. Go to /login\n2. Enter credentials",  # steps
            "User is logged in",                     # expected
            "500 Internal Server Error",             # actual
            "Firefox 120, macOS",                    # environment
            "",  # logs — optional (skip with blank)
        ]
        result = None
        for ans in answers:
            result = answer_field(sid, ans)
            if result.get("status") == "complete":
                break

        assert result is not None
        assert result["status"] == "complete"
        assert "prompt" in result
        assert "Login fails on Firefox" in result["prompt"]
        assert "500 Internal Server Error" in result["prompt"]
        assert result["skill_to_invoke"] == "debug"

    def test_assembled_prompt_contains_all_required_answers(self):
        sid = self._start("pr_review")
        fields_answers = {
            "what_changed": "Add rate limiting",
            "pr_ref": "PR #42",
            "review_focus": "Security implications",
            "context": "Brute force attacks observed",
            "acceptance_criteria": "All tests pass",
        }
        result = None
        for ans in fields_answers.values():
            result = answer_field(sid, ans)

        assert result["status"] == "complete"
        prompt = result["prompt"]
        assert "rate limiting" in prompt
        assert "Security implications" in prompt
        assert "Brute force" in prompt

    def test_session_removed_after_completion(self):
        sid = self._start("bug_report")
        answers = [
            "Bug summary", "Steps", "Expected", "Actual", "Chrome/macOS", ""
        ]
        for ans in answers:
            r = answer_field(sid, ans)
            if r.get("status") == "complete":
                break

        # Session should be gone
        status = get_session_status(sid)
        assert "error" in status


# ── skip_field ──────────────────────────────────────────────────────────────────

class TestSkipField:
    def _advance_to_optional(self):
        """Get a product_spec session to the first optional field (out_of_scope, index 5)."""
        sid = start_session("product_spec")["session_id"]
        required_answers = [
            "Auth feature",
            "Users can't reset passwords",
            "SMB employees",
            "1. Reset via email link\n2. Link expires in 30 min",
            "95% self-service rate",
        ]
        for ans in required_answers:
            answer_field(sid, ans)
        return sid

    def test_can_skip_optional_field(self):
        sid = self._advance_to_optional()
        result = skip_field(sid)
        assert "error" not in result
        # Should move forward
        assert result.get("status") in ("in_progress", "complete")

    def test_cannot_skip_required_field(self):
        sid = start_session("product_spec")["session_id"]
        result = skip_field(sid)  # first field 'name' is required
        assert "error" in result
        assert "required" in result["error"]

    def test_skip_expired_session(self):
        result = skip_field("ghost_session")
        assert "error" in result


# ── get_session_status ──────────────────────────────────────────────────────────

class TestGetSessionStatus:
    def test_returns_current_state(self):
        sid = start_session("product_spec")["session_id"]
        answer_field(sid, "My feature")
        status = get_session_status(sid)
        assert status["template"] == "product_spec"
        assert "name" in status["answers_so_far"]
        assert status["answers_so_far"]["name"] == "My feature"

    def test_unknown_session(self):
        result = get_session_status("unknown")
        assert "error" in result


# ── abandon_session ─────────────────────────────────────────────────────────────

class TestAbandonSession:
    def test_abandon_removes_session(self):
        sid = start_session("product_spec")["session_id"]
        result = abandon_session(sid)
        assert result["status"] == "abandoned"
        # Session is gone
        assert "error" in get_session_status(sid)

    def test_abandon_unknown_session(self):
        result = abandon_session("does_not_exist")
        assert "error" in result


# ── assess_prompt_quality ───────────────────────────────────────────────────────

class TestAssessPromptQuality:
    def test_empty_prompt_is_vague(self):
        result = assess_prompt_quality("")
        assert result["vague"] is True
        assert result["score"] == 0.0

    def test_short_prompt_is_vague(self):
        result = assess_prompt_quality("fix it")
        assert result["vague"] is True
        assert result["score"] < 0.5

    def test_well_formed_prompt_not_vague(self):
        result = assess_prompt_quality(
            "Review the authentication module in auth.py and identify any security vulnerabilities "
            "related to JWT token validation. Focus on expiry handling and signature verification."
        )
        assert result["vague"] is False
        assert result["score"] >= 0.5

    def test_vague_prompt_suggests_template(self):
        result = assess_prompt_quality("fix bug")
        assert "suggestion" in result
        assert "sentigent_prompt_build" in result["suggestion"]

    def test_infers_product_spec_template(self):
        result = assess_prompt_quality("build product spec")
        assert result.get("suggested_template") == "product_spec"

    def test_infers_bug_report_template(self):
        result = assess_prompt_quality("error crash")
        assert result.get("suggested_template") == "bug_report"

    def test_infers_pr_review_template(self):
        result = assess_prompt_quality("review pr")
        assert result.get("suggested_template") == "pr_review"

    def test_score_between_zero_and_one(self):
        for task in ["", "x", "fix", "implement feature", "build the product spec document"]:
            result = assess_prompt_quality(task)
            assert 0.0 <= result["score"] <= 1.0


# ── Engine integration: prompt_quality in Decision.metadata ────────────────────

class TestEnginePromptQualityIntercept:
    def test_vague_task_has_prompt_quality_in_metadata(self, tmp_db_path):
        from sentigent import Sentigent

        judge = Sentigent(profile="default", agent_id="test_pq", db_path=tmp_db_path)
        decision = judge.evaluate(
            task="fix",  # very vague
            context={},
            agent_state={"confidence": 0.9},
        )
        assert "prompt_quality" in decision.metadata
        pq = decision.metadata["prompt_quality"]
        assert pq["score"] < 0.5
        assert "sentigent_prompt_build" in pq["suggestion"]

    def test_good_task_has_no_prompt_quality_warning(self, tmp_db_path):
        from sentigent import Sentigent

        judge = Sentigent(profile="default", agent_id="test_pq2", db_path=tmp_db_path)
        decision = judge.evaluate(
            task=(
                "Review the authentication module and check for JWT token expiry handling. "
                "Flag any missing validation on the token signature field."
            ),
            context={},
            agent_state={"confidence": 0.9},
        )
        assert "prompt_quality" not in decision.metadata
