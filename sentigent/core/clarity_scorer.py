"""Phase 4: Conversation Intelligence — CLEAR framework clarity scorer.

Scores natural language task instructions on five dimensions:
  - Completeness: does the task specify what success looks like?
  - Locatability: are files, services, or code locations referenced?
  - Explicitness: are goals stated with imperative verbs, not passive hedges?
  - Ambiguity absence: no vague quantifiers, pronouns without referent, or double meanings?
  - Relevance: is the task on-topic and bounded, not sprawling?

Overall clarity score ∈ [0.0, 1.0]:
  - 0.0–0.39  → Low  (ambiguous/vague; clarification needed before acting)
  - 0.40–0.69 → Medium (usable; suggestions help)
  - 0.70–1.0  → High  (clear; proceed with confidence)

All computation is pure heuristics — zero AI, zero I/O.

Usage::

    from sentigent.core.clarity_scorer import ClarityScorer

    scorer = ClarityScorer()
    result = scorer.score("fix the auth stuff")
    # result.overall ≈ 0.22
    # result.gaps → ["No file/location specified", "No success criteria", ...]
    # result.suggestion → "Which file? What behavior? What does success look like?"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class ClarityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ClarityScore:
    """Per-dimension clarity scores + aggregated result."""

    # Individual dimensions (each 0.0–1.0)
    completeness: float = 0.0   # success criteria / acceptance conditions present
    locatability: float = 0.0   # files, paths, services, modules referenced
    explicitness: float = 0.0   # imperative verb + direct object structure
    precision: float = 0.0      # no vague quantifiers / pronoun danglers
    boundedness: float = 0.0    # scope is finite (not "everything", "all", "entire")

    # Aggregated
    overall: float = 0.0
    level: ClarityLevel = ClarityLevel.LOW

    # Actionable feedback
    gaps: list[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 3),
            "level": self.level.value,
            "dimensions": {
                "completeness": round(self.completeness, 3),
                "locatability": round(self.locatability, 3),
                "explicitness": round(self.explicitness, 3),
                "precision": round(self.precision, 3),
                "boundedness": round(self.boundedness, 3),
            },
            "gaps": self.gaps,
            "suggestion": self.suggestion,
        }


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

# Patterns that indicate success criteria are present
_SUCCESS_PATTERNS = re.compile(
    r"\b(until|so that|such that|should|must|expect|want|need|when done|"
    r"success|criterion|criteria|acceptance|passes|green|fixed|resolved|"
    r"no longer|without error|returns? \d|status [12]\d\d)\b",
    re.IGNORECASE,
)

# File / path / module references
_LOCATION_PATTERNS = re.compile(
    r"(?:"
    r"[\w/\-]+\.\w{1,6}"         # filename.ext
    r"|/[\w/\-]+"                 # /unix/path
    r"|\b[\w]+/[\w]+"             # module/submodule
    r"|\b(file|path|module|class|function|method|endpoint|table|column|service|repo)\b"
    r")",
    re.IGNORECASE,
)

# Imperative verb at the beginning of a sentence/clause
_IMPERATIVE_VERBS = re.compile(
    r"^\s*(fix|add|remove|update|delete|create|refactor|migrate|deploy|"
    r"implement|write|test|check|validate|build|replace|rename|move|convert|"
    r"ensure|make|run|enable|disable|patch|upgrade|revert|rollback|generate)\b",
    re.IGNORECASE,
)

# Vague quantifiers / hedge words / dangling pronouns
_VAGUE_PATTERNS = re.compile(
    r"\b(it|this|that|they|them|something|stuff|thing|things|bit|some|"
    r"maybe|possibly|kind of|sort of|a bit|a little|quickly|properly|"
    r"correctly|somehow|a few|several|various|appropriate|relevant|necessary)\b",
    re.IGNORECASE,
)

# Unbounded scope words
_UNBOUNDED_PATTERNS = re.compile(
    r"\b(everything|all of|the whole|entire|every|any|all the|any and all|"
    r"across the board|globally|universally)\b",
    re.IGNORECASE,
)

# Pronouns that typically have a clear referent (acceptable)
_ACCEPTABLE_PRONOUNS = re.compile(
    r"\b(it|this|that)\b.*\b(file|class|function|method|bug|error|issue|test)\b",
    re.IGNORECASE,
)

# Weights for each dimension in the overall score
_DIMENSION_WEIGHTS = {
    "completeness": 0.25,
    "locatability": 0.25,
    "explicitness": 0.20,
    "precision": 0.15,
    "boundedness": 0.15,
}


class ClarityScorer:
    """Score task instructions on the CLEAR framework (heuristic, zero AI)."""

    def score(self, task: str, conversation_history: list[str] | None = None) -> ClarityScore:
        """Score a task instruction.

        Args:
            task: The natural language task description to evaluate.
            conversation_history: Prior turns in the conversation (allows
                pronoun resolution across turns).

        Returns:
            ClarityScore with per-dimension scores, gaps, and a suggestion.
        """
        if not task or not task.strip():
            return ClarityScore(
                gaps=["Task is empty"],
                suggestion="Please describe what you want the agent to do.",
            )

        task = task.strip()
        # Combine task with conversation history for context
        full_context = " ".join(conversation_history or []) + " " + task

        completeness = self._score_completeness(task)
        locatability = self._score_locatability(task, full_context)
        explicitness = self._score_explicitness(task)
        precision = self._score_precision(task)
        boundedness = self._score_boundedness(task)

        overall = (
            completeness * _DIMENSION_WEIGHTS["completeness"]
            + locatability * _DIMENSION_WEIGHTS["locatability"]
            + explicitness * _DIMENSION_WEIGHTS["explicitness"]
            + precision * _DIMENSION_WEIGHTS["precision"]
            + boundedness * _DIMENSION_WEIGHTS["boundedness"]
        )
        overall = round(min(1.0, max(0.0, overall)), 3)

        if overall >= 0.70:
            level = ClarityLevel.HIGH
        elif overall >= 0.40:
            level = ClarityLevel.MEDIUM
        else:
            level = ClarityLevel.LOW

        gaps = self._identify_gaps(task, completeness, locatability, explicitness, precision, boundedness)
        suggestion = self._generate_suggestion(task, gaps)

        return ClarityScore(
            completeness=round(completeness, 3),
            locatability=round(locatability, 3),
            explicitness=round(explicitness, 3),
            precision=round(precision, 3),
            boundedness=round(boundedness, 3),
            overall=overall,
            level=level,
            gaps=gaps,
            suggestion=suggestion,
        )

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    def _score_completeness(self, task: str) -> float:
        """Presence of success criteria / acceptance conditions."""
        if _SUCCESS_PATTERNS.search(task):
            return 1.0
        # Longer tasks are more likely to contain implicit success criteria
        word_count = len(task.split())
        if word_count > 30:
            return 0.5
        if word_count > 15:
            return 0.3
        return 0.0

    def _score_locatability(self, task: str, context: str) -> float:
        """Are code locations (files, modules, services) mentioned?"""
        matches = _LOCATION_PATTERNS.findall(context)
        if len(matches) >= 3:
            return 1.0
        if len(matches) == 2:
            return 0.7
        if len(matches) == 1:
            return 0.4
        return 0.0

    def _score_explicitness(self, task: str) -> float:
        """Does the task start with an imperative verb?"""
        if _IMPERATIVE_VERBS.match(task):
            return 1.0
        # Check if imperative appears in the first sentence
        first_sentence = re.split(r"[.!?\n]", task)[0]
        if _IMPERATIVE_VERBS.match(first_sentence.strip()):
            return 0.8
        # Passive / interrogative forms
        if re.match(r"\b(can you|could you|please|would you|i need|i want)\b", task, re.IGNORECASE):
            return 0.4
        return 0.2

    def _score_precision(self, task: str) -> float:
        """Absence of vague language and dangling pronouns."""
        vague_count = len(_VAGUE_PATTERNS.findall(task))
        word_count = max(len(task.split()), 1)
        vague_ratio = vague_count / word_count

        # Acceptable pronouns like "it in middleware.py" don't penalize
        if _ACCEPTABLE_PRONOUNS.search(task):
            vague_count = max(0, vague_count - 1)
            vague_ratio = vague_count / word_count

        if vague_ratio == 0:
            return 1.0
        if vague_ratio < 0.05:
            return 0.8
        if vague_ratio < 0.10:
            return 0.5
        if vague_ratio < 0.20:
            return 0.3
        return 0.0

    def _score_boundedness(self, task: str) -> float:
        """Is the scope finite rather than unbounded?"""
        if _UNBOUNDED_PATTERNS.search(task):
            return 0.0
        # Tasks with enumerations or explicit limits are more bounded
        if re.search(r"\b(only|just|specifically|in particular|limit(ed)? to)\b", task, re.IGNORECASE):
            return 1.0
        return 0.8  # default: assume bounded unless proven otherwise

    # ------------------------------------------------------------------
    # Gaps + suggestions
    # ------------------------------------------------------------------

    def _identify_gaps(
        self,
        task: str,
        completeness: float,
        locatability: float,
        explicitness: float,
        precision: float,
        boundedness: float,
    ) -> list[str]:
        gaps: list[str] = []
        if completeness < 0.4:
            gaps.append("No success criteria (what does 'done' look like?)")
        if locatability < 0.4:
            gaps.append("No file, module, or service location specified")
        if explicitness < 0.5:
            gaps.append("Task is not phrased as a clear imperative command")
        if precision < 0.5:
            gaps.append("Vague or ambiguous language detected")
        if boundedness < 0.5:
            gaps.append("Scope appears unbounded (\"all\", \"everything\", etc.)")
        return gaps

    def _generate_suggestion(self, task: str, gaps: list[str]) -> str:
        if not gaps:
            return ""

        parts: list[str] = []
        if "No file, module, or service location specified" in gaps:
            parts.append("Which file or service?")
        if "No success criteria" in gaps:
            parts.append("What does success look like?")
        if "Vague or ambiguous language" in gaps:
            parts.append("Can you be more specific?")
        if "Scope appears unbounded" in gaps:
            parts.append("Limit the scope — which specific parts?")
        if "not phrased as a clear imperative" in " ".join(gaps):
            parts.append("Start with an action verb (Fix / Add / Update).")

        if not parts:
            return "Provide more detail about the task."
        return " ".join(parts)
