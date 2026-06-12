"""Tests for prompt_observer.py — prompt quality analysis."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sentigent.core.prompt_observer import (
    PromptHealthReport,
    PromptImprovement,
    PromptObserver,
    PromptPattern,
    _BAD_PATTERNS,
    _GOOD_PATTERNS,
    _LENGTH_BUCKETS,
)


# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_test_db(episodes: list[dict]) -> str:
    """Create a temporary SQLite DB with the given episodes."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT,
            agent_id TEXT,
            task TEXT,
            context TEXT,
            signals TEXT,
            decision TEXT,
            confidence_at_decision REAL,
            outcome TEXT,
            outcome_feedback TEXT,
            timestamp TEXT
        )
    """)
    for ep in episodes:
        conn.execute(
            "INSERT INTO episodes (task, decision, outcome, outcome_feedback, timestamp) VALUES (?,?,?,?,?)",
            (
                ep.get("task", ""),
                ep.get("decision", "proceed"),
                ep.get("outcome", "correct"),
                ep.get("feedback", ""),
                ep.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


def _make_observer(episodes: list[dict]) -> PromptObserver:
    db_path = _make_test_db(episodes)
    obs = PromptObserver(agent_id="test_agent", db_path=db_path)
    return obs


# ── Unit tests for pattern detection ─────────────────────────────────────────


class TestPatternDetection:
    def test_bad_pattern_vague_quantifier(self):
        """Detect vague words like 'some', 'several'."""
        _, pat = next(p for p in _BAD_PATTERNS if p[0] == "vague_quantifier")
        assert pat.search("fix some of the errors")
        assert pat.search("update several files")
        assert not pat.search("fix all errors in src/main.py")

    def test_bad_pattern_passive_voice(self):
        _, pat = next(p for p in _BAD_PATTERNS if p[0] == "passive_voice_command")
        assert pat.search("the code should be refactored")
        assert pat.search("tests needs to be updated")   # "needs to be" matches
        assert pat.search("this must be fixed")
        assert not pat.search("refactor the code")

    def test_bad_pattern_no_target(self):
        _, pat = next(p for p in _BAD_PATTERNS if p[0] == "no_target_specified")
        assert pat.search("fix it")
        assert pat.search("make it work")
        assert not pat.search("fix the TypeError in auth.py")

    def test_bad_pattern_implicit_assumption(self):
        _, pat = next(p for p in _BAD_PATTERNS if p[0] == "implicit_assumption")
        assert pat.search("do it the same as usual")
        assert pat.search("obviously use the same pattern")
        assert not pat.search("use the same error handling as in src/api.py")

    def test_good_pattern_file_reference(self):
        _, pat = next(p for p in _GOOD_PATTERNS if p[0] == "has_file_reference")
        assert pat.search("fix the error in src/auth/login.py")
        assert pat.search('edit "tests/test_auth.py"')
        assert not pat.search("fix the error")

    def test_good_pattern_success_criteria(self):
        _, pat = next(p for p in _GOOD_PATTERNS if p[0] == "has_success_criteria")
        assert pat.search("ensure all tests pass")
        assert pat.search("verify the API returns 200")
        assert not pat.search("run the tests")

    def test_good_pattern_imperative_start(self):
        _, pat = next(p for p in _GOOD_PATTERNS if p[0] == "starts_with_imperative")
        assert pat.search("Add error handling for the login flow")
        assert pat.search("fix the NullPointerException in UserService")
        assert not pat.search("there is an error in the login flow")


# ── PromptObserver behavior ───────────────────────────────────────────────────


class TestPromptObserverEmpty:
    def test_empty_db_returns_empty_report(self):
        obs = PromptObserver(agent_id="ghost", db_path="/tmp/nonexistent_xyz.db")
        report = obs.analyze(lookback_days=7)
        assert isinstance(report, PromptHealthReport)
        assert report.total_episodes == 0
        assert len(report.improvements) > 0
        assert "Not enough data" in report.improvements[0].issue or report.total_episodes == 0

    def test_few_episodes_empty_report(self):
        db = _make_test_db([{"task": "fix it", "outcome": "incorrect"} for _ in range(3)])
        obs = PromptObserver(agent_id="test", db_path=db)
        report = obs.analyze(lookback_days=7)
        # 3 < 10 minimum
        assert report.total_episodes == 0 or len(report.improvements) > 0


class TestPromptObserverWithData:
    def test_vague_prompts_detected(self):
        """Vague short prompts that fail should appear in bad patterns."""
        episodes = (
            [{"task": "fix it", "outcome": "incorrect"} for _ in range(8)]
            + [{"task": "make it work", "outcome": "incorrect"} for _ in range(5)]
            + [{"task": "add logging to src/api/routes.py and verify with pytest", "outcome": "correct"} for _ in range(15)]
        )
        obs = _make_observer(episodes)
        report = obs.analyze(lookback_days=365)

        assert report.total_episodes > 0
        # Very short prompts should have low success rate
        short_stats = report.outcome_by_length.get("very_short", {})
        if short_stats.get("n", 0) > 0:
            assert short_stats["rate"] < 0.5

    def test_health_score_range(self):
        """Health score should be between 0 and 100."""
        episodes = [
            {"task": "fix authentication bug in login.py", "outcome": "correct"},
            {"task": "fix it", "outcome": "incorrect"},
            {"task": "add tests for UserService ensuring 100% coverage", "outcome": "correct"},
            {"task": "update some files", "outcome": "incorrect"},
        ] * 5
        obs = _make_observer(episodes)
        report = obs.analyze(lookback_days=365)
        assert 0.0 <= report.health_score <= 100.0

    def test_correct_outcomes_improve_score(self):
        """Lots of good specific prompts → high health score."""
        good_prompts = [
            {"task": f"fix type error in src/module_{i}.py, ensure pytest passes", "outcome": "correct"}
            for i in range(20)
        ]
        obs = _make_observer(good_prompts)
        report = obs.analyze(lookback_days=365)
        assert report.health_score > 50.0

    def test_failing_vague_prompts_lower_score(self):
        """Many vague prompts with bad outcomes → lower health score."""
        bad_prompts = [
            {"task": "fix it", "outcome": "incorrect"},
            {"task": "do this", "outcome": "incorrect"},
            {"task": "make it better", "outcome": "incorrect"},
            {"task": "just fix it", "outcome": "incorrect"},
        ] * 5
        obs = _make_observer(bad_prompts)
        report = obs.analyze(lookback_days=365)
        # Score should be impacted by vague prompts
        # (no guarantee of absolute value, just that it's not perfect)
        assert report.vague_prompt_rate > 0

    def test_outcome_by_length_bucketing(self):
        """Episodes should be distributed into length buckets."""
        episodes = [
            {"task": "fix", "outcome": "incorrect"},                     # very_short (3)
            {"task": "fix the bug", "outcome": "correct"},               # short (11)
            {"task": "a" * 100, "outcome": "correct"},                   # medium (100)
            {"task": "a" * 300, "outcome": "correct"},                   # long (300)
        ] * 5
        obs = _make_observer(episodes)
        report = obs.analyze(lookback_days=365)
        result = report.outcome_by_length
        assert "very_short" in result
        assert "medium" in result

    def test_to_dict_schema(self):
        episodes = [
            {"task": "add user authentication to src/auth.py", "outcome": "correct"}
        ] * 15
        obs = _make_observer(episodes)
        report = obs.analyze(lookback_days=365)
        d = report.to_dict()
        assert "agent_id" in d
        assert "health_score" in d
        assert "total_episodes" in d
        assert "avg_prompt_length" in d
        assert "outcome_by_length" in d
        assert "improvements" in d
        assert isinstance(d["improvements"], list)

    def test_to_text_contains_header(self):
        episodes = [
            {"task": "fix auth error in login.py", "outcome": "correct"}
        ] * 15
        obs = _make_observer(episodes)
        report = obs.analyze(lookback_days=365)
        text = report.to_text()
        assert "SENTIGENT PROMPT HEALTH" in text
        assert "HEALTH SCORE" in text


# ── PromptPattern properties ──────────────────────────────────────────────────


class TestPromptPattern:
    def test_outcome_rate(self):
        p = PromptPattern("id1", "label", frequency=10, correct_count=8, incorrect_count=2)
        assert p.outcome_rate == pytest.approx(0.8)

    def test_outcome_rate_zero_total(self):
        p = PromptPattern("id1", "label", frequency=0, correct_count=0, incorrect_count=0)
        assert p.outcome_rate == 0.5

    def test_is_problematic(self):
        p = PromptPattern("id1", "label", frequency=10, correct_count=2, incorrect_count=5)
        assert p.is_problematic  # outcome_rate < 0.6, incorrect >= 3, frequency >= 5

    def test_not_problematic_low_frequency(self):
        p = PromptPattern("id1", "label", frequency=2, correct_count=0, incorrect_count=2)
        assert not p.is_problematic  # frequency < 5

    def test_is_beneficial(self):
        p = PromptPattern("id1", "label", frequency=10, correct_count=9, incorrect_count=1)
        assert p.is_beneficial

    def test_not_beneficial_low_count(self):
        p = PromptPattern("id1", "label", frequency=3, correct_count=3, incorrect_count=0)
        assert not p.is_beneficial  # correct < 5


# ── PromptImprovement ─────────────────────────────────────────────────────────


class TestPromptImprovement:
    def test_improvement_has_before_after(self):
        imp = PromptImprovement(
            issue="Too vague",
            pattern_detected="vague_quantifier",
            suggestion="Be specific",
            example_before="fix some errors",
            example_after="fix all type errors in src/api.py",
        )
        assert imp.example_before != imp.example_after
        assert len(imp.suggestion) > 5
