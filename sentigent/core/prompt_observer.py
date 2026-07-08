"""Prompt Observer — observe prompts and help users improve agent interactions.

The user's insight: "we improve the prompts, observe prompt and user behavior
and help them improve their interaction with agent."

This module tracks what kinds of prompts lead to good vs bad outcomes, detects
problematic prompt patterns (vague, ambiguous, implicit assumptions), and
generates specific rewrite suggestions so humans can communicate better with
their AI agents.

The observer is pure statistics — no AI required. The AI synthesis in
InteractionCoach uses the observer's findings as part of its analysis.

Key metrics tracked:
- Prompt length vs outcome correlation
- Presence of success criteria (explicit vs implicit goals)
- Ambiguity indicators (passive voice, vague quantifiers, missing scope)
- Command clarity (imperative verb at start vs buried instruction)
- Context richness (mentions of files, paths, conditions vs bare commands)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sentigent.prompt_observer")


# ── Pattern definitions ──────────────────────────────────────────────────────

# Patterns that correlate with good prompts (command clarity, context richness)
_GOOD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("has_file_reference", re.compile(r'["\']?[\w\-/]+\.\w{2,4}["\']?|src/|tests/')),
    ("has_success_criteria", re.compile(r'\b(should|must|ensure|verify|confirm|pass|succeed|return)\b', re.I)),
    ("has_explicit_scope", re.compile(r'\b(only|just|specifically|in\s+the\s+\w+\s+(file|dir|module|class|function))\b', re.I)),
    ("starts_with_imperative", re.compile(r'^(add|fix|update|create|delete|refactor|test|check|run|build|deploy|write|read|find|implement|remove|change|move|copy|rename)\b', re.I)),
    ("has_condition_or_context", re.compile(r'\b(if|when|after|before|because|since|so that|in order to)\b', re.I)),
]

# Patterns that correlate with problematic prompts
_BAD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("vague_quantifier", re.compile(r'\b(some|a few|several|many|various|certain|appropriate|proper|good|better|best|nice|clean)\b', re.I)),
    ("passive_voice_command", re.compile(r'\b(should be|needs to be|has to be|ought to be|must be)\b', re.I)),
    ("no_target_specified", re.compile(r'^(fix it|make it work|do it|handle this|deal with|take care of|look at|check out)\s*$', re.I)),
    ("implicit_assumption", re.compile(r'\b(obviously|clearly|of course|as usual|like before|same as|just|simply)\b', re.I)),
    ("ambiguous_pronoun", re.compile(r'\b(it|this|that|these|those)\b(?!\s+\w+\s+(file|function|class|method|variable|table|column|field))', re.I)),
]

# Minimum prompt length buckets (chars) for analysis
_LENGTH_BUCKETS = [
    (0, 30, "very_short"),
    (30, 80, "short"),
    (80, 200, "medium"),
    (200, 500, "long"),
    (500, 99999, "very_long"),
]


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PromptPattern:
    """A pattern detected in prompts, with its outcome correlation."""
    pattern_id: str
    label: str
    frequency: int                  # how many episodes have this pattern
    correct_count: int
    incorrect_count: int

    @property
    def outcome_rate(self) -> float:
        """Success rate when this pattern is present."""
        total = self.correct_count + self.incorrect_count
        return self.correct_count / total if total > 0 else 0.5

    @property
    def is_problematic(self) -> bool:
        """Pattern is problematic if it appears often and correlates with failures."""
        return (
            self.incorrect_count >= 3
            and self.outcome_rate < 0.6
            and self.frequency >= 5
        )

    @property
    def is_beneficial(self) -> bool:
        """Pattern is beneficial if it appears often and correlates with success."""
        return (
            self.correct_count >= 5
            and self.outcome_rate >= 0.85
            and self.frequency >= 5
        )


@dataclass
class PromptImprovement:
    """A specific rewrite suggestion for a detected pattern."""
    issue: str
    pattern_detected: str
    suggestion: str
    example_before: str             # from actual failed episodes
    example_after: str              # improved version


@dataclass
class PromptHealthReport:
    """Full prompt quality analysis for an agent."""
    agent_id: str
    generated_at: str
    lookback_days: int
    total_episodes: int

    # Aggregate metrics
    avg_prompt_length: float
    median_prompt_length: float
    vague_prompt_rate: float        # fraction of prompts that are very_short or vague
    health_score: float             # 0–100 overall score

    # Per-length-bucket success rates
    outcome_by_length: dict[str, dict[str, Any]]  # bucket → {rate, n}

    # Pattern analysis
    bad_patterns: list[PromptPattern]
    good_patterns: list[PromptPattern]

    # Actionable improvements
    improvements: list[PromptImprovement]

    # Top failing prompt examples (for display)
    failing_examples: list[str]
    succeeding_examples: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "total_episodes": self.total_episodes,
            "avg_prompt_length": round(self.avg_prompt_length, 1),
            "median_prompt_length": round(self.median_prompt_length, 1),
            "vague_prompt_rate": round(self.vague_prompt_rate, 3),
            "health_score": round(self.health_score, 1),
            "outcome_by_length": self.outcome_by_length,
            "bad_patterns": [
                {
                    "id": p.pattern_id,
                    "label": p.label,
                    "frequency": p.frequency,
                    "outcome_rate": round(p.outcome_rate, 3),
                }
                for p in self.bad_patterns
            ],
            "good_patterns": [
                {
                    "id": p.pattern_id,
                    "label": p.label,
                    "frequency": p.frequency,
                    "outcome_rate": round(p.outcome_rate, 3),
                }
                for p in self.good_patterns
            ],
            "improvements": [
                {
                    "issue": imp.issue,
                    "suggestion": imp.suggestion,
                    "example_before": imp.example_before,
                    "example_after": imp.example_after,
                }
                for imp in self.improvements
            ],
            "failing_examples": self.failing_examples,
            "succeeding_examples": self.succeeding_examples,
        }

    def to_text(self) -> str:
        lines = [
            f"\n{'='*64}",
            f"  SENTIGENT PROMPT HEALTH — {self.agent_id}",
            f"  Generated: {self.generated_at[:16]}  |  Window: {self.lookback_days} days",
            f"{'='*64}\n",
            f"  HEALTH SCORE: {self.health_score:.0f}/100  "
            f"({'Excellent' if self.health_score >= 80 else 'Good' if self.health_score >= 60 else 'Needs work'})",
            f"  Episodes analyzed: {self.total_episodes}",
            f"  Avg prompt length: {self.avg_prompt_length:.0f} chars",
            f"  Vague prompt rate: {self.vague_prompt_rate:.0%}\n",
            f"  OUTCOME BY PROMPT LENGTH",
            f"  {'─'*48}",
        ]
        for bucket_name, stats in self.outcome_by_length.items():
            if stats.get("n", 0) == 0:
                continue
            bar = "▓" * int(stats["rate"] * 20) + "░" * (20 - int(stats["rate"] * 20))
            lines.append(
                f"  {bucket_name:<12} [{bar}]  {stats['rate']:.0%} success (n={stats['n']})"
            )

        if self.bad_patterns:
            lines += [f"\n  PROBLEMATIC PATTERNS", f"  {'─'*48}"]
            for p in self.bad_patterns[:5]:
                lines.append(f"  ⚠ {p.label:<35} {p.outcome_rate:.0%} success rate (n={p.frequency})")

        if self.good_patterns:
            lines += [f"\n  BENEFICIAL PATTERNS", f"  {'─'*48}"]
            for p in self.good_patterns[:5]:
                lines.append(f"  ✓ {p.label:<35} {p.outcome_rate:.0%} success rate (n={p.frequency})")

        if self.improvements:
            lines += [f"\n  HOW TO IMPROVE YOUR PROMPTS", f"  {'─'*48}"]
            for i, imp in enumerate(self.improvements, 1):
                lines.append(f"\n  {i}. {imp.issue}")
                lines.append(f"     Suggestion: {imp.suggestion}")
                if imp.example_before:
                    lines.append(f"     Before: \"{imp.example_before[:60]}\"")
                    lines.append(f"     After:  \"{imp.example_after[:60]}\"")

        lines.append(f"\n{'='*64}\n")
        return "\n".join(lines)


# ── Prompt Observer ──────────────────────────────────────────────────────────


class PromptObserver:
    """Observes prompt quality patterns from episode history.

    This class loads episodes from SQLite and analyzes the `task` field
    (which is the prompt/instruction the user gave the agent) to find:
    - Which prompt styles lead to correct vs incorrect outcomes
    - What patterns correlate with failures
    - Specific rewrite examples to help users improve

    Usage:
        observer = PromptObserver(agent_id="my_agent")
        report = observer.analyze(lookback_days=30)
        print(report.to_text())
    """

    def __init__(self, agent_id: str = "", db_path: str | None = None) -> None:
        if not agent_id:
            from sentigent.config import get_config
            agent_id = get_config().agent_id
        self.agent_id = agent_id
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = Path.home() / ".sentigent" / f"memory_{agent_id}.db"

    def analyze(self, lookback_days: int = 30) -> PromptHealthReport:
        """Run full prompt quality analysis."""
        episodes = self._load_episodes(lookback_days)
        if len(episodes) < 10:
            return self._empty_report(lookback_days, f"Only {len(episodes)} scored episodes in window")

        lengths = [len(ep.get("task", "")) for ep in episodes]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
        sorted_lengths = sorted(lengths)
        mid = len(sorted_lengths) // 2
        median_len = sorted_lengths[mid] if sorted_lengths else 0

        # Vague rate = fraction of episodes with very short prompts (< 30 chars)
        vague_rate = sum(1 for l in lengths if l < 30) / len(lengths)

        outcome_by_length = self._outcome_by_length(episodes)
        bad_patterns, good_patterns = self._analyze_patterns(episodes)
        improvements = self._generate_improvements(bad_patterns, good_patterns, episodes)
        health_score = self._compute_health_score(
            vague_rate, bad_patterns, good_patterns, outcome_by_length
        )

        # Collect examples
        failing = [
            ep["task"][:80] for ep in episodes
            if ep.get("outcome") == "incorrect" and len(ep.get("task", "")) > 5
        ][:5]
        succeeding = [
            ep["task"][:80] for ep in episodes
            if ep.get("outcome") == "correct" and len(ep.get("task", "")) > 30
        ][:5]

        return PromptHealthReport(
            agent_id=self.agent_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            lookback_days=lookback_days,
            total_episodes=len(episodes),
            avg_prompt_length=avg_len,
            median_prompt_length=median_len,
            vague_prompt_rate=vague_rate,
            health_score=health_score,
            outcome_by_length=outcome_by_length,
            bad_patterns=[p for p in bad_patterns if p.is_problematic],
            good_patterns=[p for p in good_patterns if p.is_beneficial],
            improvements=improvements,
            failing_examples=failing,
            succeeding_examples=succeeding,
        )

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_episodes(self, lookback_days: int) -> list[dict[str, Any]]:
        if not self._db_path.exists():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT task, decision, outcome, outcome_feedback, timestamp
                   FROM episodes WHERE timestamp >= ?
                   AND outcome IN ('correct', 'incorrect')
                   ORDER BY timestamp""",
                (cutoff,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("Failed to load episodes for prompt analysis: %s", exc)
            return []

    # ── Analysis ──────────────────────────────────────────────────────────────

    def _outcome_by_length(self, episodes: list[dict]) -> dict[str, dict[str, Any]]:
        """Compute success rates per prompt length bucket."""
        buckets: dict[str, list[dict]] = {name: [] for _, _, name in _LENGTH_BUCKETS}

        for ep in episodes:
            task_len = len(ep.get("task", ""))
            for low, high, name in _LENGTH_BUCKETS:
                if low <= task_len < high:
                    buckets[name].append(ep)
                    break

        result: dict[str, dict[str, Any]] = {}
        for name, eps in buckets.items():
            if not eps:
                result[name] = {"n": 0, "rate": 0.0}
                continue
            correct = sum(1 for e in eps if e.get("outcome") == "correct")
            total = len(eps)
            result[name] = {
                "n": total,
                "rate": round(correct / total, 3),
                "correct": correct,
                "incorrect": total - correct,
            }
        return result

    def _analyze_patterns(
        self, episodes: list[dict]
    ) -> tuple[list[PromptPattern], list[PromptPattern]]:
        """Analyze which prompt patterns correlate with outcomes."""
        # Count patterns in good vs bad episodes
        bad_pattern_counts: dict[str, dict[str, int]] = {
            pid: {"correct": 0, "incorrect": 0, "total": 0}
            for pid, _ in _BAD_PATTERNS
        }
        good_pattern_counts: dict[str, dict[str, int]] = {
            pid: {"correct": 0, "incorrect": 0, "total": 0}
            for pid, _ in _GOOD_PATTERNS
        }

        for ep in episodes:
            task = ep.get("task", "")
            outcome = ep.get("outcome", "neutral")
            if outcome not in ("correct", "incorrect"):
                continue

            for pid, pat in _BAD_PATTERNS:
                if pat.search(task):
                    bad_pattern_counts[pid]["total"] += 1
                    bad_pattern_counts[pid][outcome] += 1

            for pid, pat in _GOOD_PATTERNS:
                if pat.search(task):
                    good_pattern_counts[pid]["total"] += 1
                    good_pattern_counts[pid][outcome] += 1

        # Build label maps
        bad_label_map = {pid: label for pid, label in _BAD_PATTERNS}  # type: ignore[misc]
        good_label_map = {pid: label for pid, label in _GOOD_PATTERNS}  # type: ignore[misc]

        bad_patterns = [
            PromptPattern(
                pattern_id=pid,
                label=self._format_pattern_label(bad_label_map[pid].pattern, "bad"),  # type: ignore[union-attr]
                frequency=counts["total"],
                correct_count=counts["correct"],
                incorrect_count=counts["incorrect"],
            )
            for pid, counts in bad_pattern_counts.items()
            if counts["total"] > 0
        ]

        good_patterns = [
            PromptPattern(
                pattern_id=pid,
                label=self._format_pattern_label(good_label_map[pid].pattern, "good"),  # type: ignore[union-attr]
                frequency=counts["total"],
                correct_count=counts["correct"],
                incorrect_count=counts["incorrect"],
            )
            for pid, counts in good_pattern_counts.items()
            if counts["total"] > 0
        ]

        return bad_patterns, good_patterns

    def _format_pattern_label(self, pattern_id: str, kind: str) -> str:
        """Convert pattern_id to human readable label."""
        labels = {
            # bad
            "vague_quantifier": "Uses vague quantifiers (some/many/various)",
            "passive_voice_command": "Passive voice instruction",
            "no_target_specified": "No explicit target specified",
            "implicit_assumption": "Implicit assumptions (obviously/as usual)",
            "ambiguous_pronoun": "Ambiguous pronouns (it/this/that)",
            # good
            "has_file_reference": "References specific files/paths",
            "has_success_criteria": "States success criteria explicitly",
            "has_explicit_scope": "Explicitly scopes the change",
            "starts_with_imperative": "Starts with action verb (imperative)",
            "has_condition_or_context": "Provides context or conditions",
        }
        return labels.get(pattern_id, pattern_id)

    def _generate_improvements(
        self,
        bad_patterns: list[PromptPattern],
        good_patterns: list[PromptPattern],
        episodes: list[dict],
    ) -> list[PromptImprovement]:
        """Generate specific improvement suggestions based on observed patterns."""
        improvements: list[PromptImprovement] = []

        # Collect examples by pattern
        examples_by_bad_pattern: dict[str, list[str]] = defaultdict(list)
        for ep in episodes:
            if ep.get("outcome") != "incorrect":
                continue
            task = ep.get("task", "")
            for pid, pat in _BAD_PATTERNS:
                if pat.search(task):
                    examples_by_bad_pattern[pid].append(task[:80])

        # Generate improvement for each problematic bad pattern
        for pattern in bad_patterns:
            if not pattern.is_problematic:
                continue
            pid = pattern.pattern_id
            example = examples_by_bad_pattern.get(pid, [""])[0]
            imp = self._improvement_for_pattern(pid, example)
            if imp:
                improvements.append(imp)

        # If prompts are too short, add a length improvement
        # (but only if not already covered by a specific pattern)
        short_data = {}
        for ep in episodes:
            if len(ep.get("task", "")) < 30 and ep.get("outcome") == "incorrect":
                short_data["count"] = short_data.get("count", 0) + 1
                if "example" not in short_data:
                    short_data["example"] = ep.get("task", "")

        if short_data.get("count", 0) >= 3:
            improvements.append(PromptImprovement(
                issue="Prompts under 30 characters frequently fail",
                pattern_detected="very_short_prompt",
                suggestion=(
                    "Add specificity: include the target file/function, "
                    "what you want done, and what success looks like."
                ),
                example_before=short_data.get("example", "fix it"),
                example_after=(
                    "Fix the validation error in src/auth/login.py "
                    "— the email regex should accept plus signs"
                ),
            ))

        return improvements[:5]  # cap at 5 most impactful

    def _improvement_for_pattern(self, pid: str, example: str) -> PromptImprovement | None:
        """Return a specific improvement suggestion for a pattern ID."""
        mapping: dict[str, PromptImprovement] = {
            "vague_quantifier": PromptImprovement(
                issue="Vague quantifiers make tasks ambiguous",
                pattern_detected=pid,
                suggestion=(
                    "Replace 'some', 'several', 'various' with exact numbers or criteria. "
                    "E.g. 'fix some errors' → 'fix all type errors in src/api/routes.py'"
                ),
                example_before=example or "fix some of the errors",
                example_after="fix all type errors in src/api/routes.py (run mypy first)",
            ),
            "passive_voice_command": PromptImprovement(
                issue="Passive voice creates ambiguity about who/what acts",
                pattern_detected=pid,
                suggestion=(
                    "Use active imperative: 'it should be refactored' → "
                    "'refactor UserService.validate() to use dataclasses'"
                ),
                example_before=example or "the test file should be updated",
                example_after="update tests/test_auth.py to cover the new OAuth flow",
            ),
            "implicit_assumption": PromptImprovement(
                issue="Implicit assumptions ('obviously', 'as usual') skip needed context",
                pattern_detected=pid,
                suggestion=(
                    "Spell out the assumption. 'as usual' → specify the exact convention "
                    "or link to the relevant pattern in the codebase."
                ),
                example_before=example or "do it the same as usual",
                example_after=(
                    "use the same error handling pattern as in src/api/payments.py: "
                    "try/except → log + return {'error': str(e)}"
                ),
            ),
            "ambiguous_pronoun": PromptImprovement(
                issue="Ambiguous pronouns (it/this/that) require inference",
                pattern_detected=pid,
                suggestion=(
                    "Replace pronouns with specific names: "
                    "'fix it' → 'fix the NullPointerException in UserController.get_by_id()'"
                ),
                example_before=example or "can you fix it?",
                example_after="fix the KeyError in config.py line 42 — add a default for missing keys",
            ),
            "no_target_specified": PromptImprovement(
                issue="No target specified — agent must guess where to make changes",
                pattern_detected=pid,
                suggestion=(
                    "Always name the target: file, function, class, or feature. "
                    "'make it work' → 'make the /login endpoint return 401 instead of 500 on bad credentials'"
                ),
                example_before=example or "make it work",
                example_after=(
                    "make GET /api/v1/users/:id return 404 (not 500) "
                    "when user_id doesn't exist in the database"
                ),
            ),
        }
        return mapping.get(pid)

    def _compute_health_score(
        self,
        vague_rate: float,
        bad_patterns: list[PromptPattern],
        good_patterns: list[PromptPattern],
        outcome_by_length: dict[str, dict[str, Any]],
    ) -> float:
        """Compute an overall prompt health score from 0 to 100."""
        score = 100.0

        # Penalize vague prompts
        score -= vague_rate * 30

        # Penalize problematic patterns
        for p in bad_patterns:
            if p.is_problematic:
                penalty = (1 - p.outcome_rate) * 10
                score -= min(penalty, 15)

        # Reward beneficial patterns
        total_good = sum(1 for p in good_patterns if p.is_beneficial)
        score += min(total_good * 3, 15)

        # Penalize if very_short prompts have very low success rates
        short_stats = outcome_by_length.get("very_short", {})
        if short_stats.get("n", 0) >= 5 and short_stats.get("rate", 1.0) < 0.5:
            score -= 10

        return max(0.0, min(100.0, score))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _empty_report(self, lookback_days: int, reason: str = "") -> PromptHealthReport:
        return PromptHealthReport(
            agent_id=self.agent_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            lookback_days=lookback_days,
            total_episodes=0,
            avg_prompt_length=0.0,
            median_prompt_length=0.0,
            vague_prompt_rate=0.0,
            health_score=50.0,
            outcome_by_length={},
            bad_patterns=[],
            good_patterns=[],
            improvements=[PromptImprovement(
                issue=reason or "Not enough data yet",
                pattern_detected="",
                suggestion="Keep using the agent to build up pattern history.",
                example_before="",
                example_after="",
            )],
            failing_examples=[],
            succeeding_examples=[],
        )
