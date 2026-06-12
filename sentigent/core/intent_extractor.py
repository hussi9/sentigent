"""Phase 4: Conversation Intelligence — Intent Extractor.

Parses a natural language task description into a StructuredIntent that can
feed directly into sentigent_start_task().

Design principle: zero AI, zero I/O. Pure regex + heuristics so the extractor
adds <1ms overhead and works offline.

Output StructuredIntent maps 1-to-1 with sentigent_start_task() parameters:

    intent = IntentExtractor().extract("Fix JWT expiry bug in auth/middleware.py")
    # intent.goal       → "Fix JWT expiry bug"
    # intent.scope      → ["auth/middleware.py"]
    # intent.constraints → []
    # intent.success_criteria → []

Usage::

    from sentigent.core.intent_extractor import IntentExtractor

    extractor = IntentExtractor()
    intent = extractor.extract(
        "Fix the 401 error users are getting — it's in auth/middleware.py",
        conversation_history=["which file?", "auth/middleware.py"],
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class StructuredIntent:
    """Parsed intent ready for sentigent_start_task()."""

    goal: str = ""
    """Primary objective — imperative sentence (no location details)."""

    scope: list[str] = field(default_factory=list)
    """Files, paths, modules, services, tables, or API endpoints in scope."""

    constraints: list[str] = field(default_factory=list)
    """Things NOT to do or boundaries to respect."""

    success_criteria: list[str] = field(default_factory=list)
    """Observable conditions that indicate the task is done."""

    specificity: float = 0.0
    """0.0–1.0. Higher = more specific (goal + scope + criteria present)."""

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "scope": self.scope,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
            "specificity": round(self.specificity, 3),
        }

    def to_start_task_kwargs(self) -> dict:
        """Return kwargs for sentigent_start_task()."""
        return {
            "goal": self.goal,
            "scope": self.scope,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
        }


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# File / module / service scope detection
_SCOPE_PATTERNS = [
    re.compile(r"[\w\-/]+\.\w{1,6}"),          # filename.ext
    re.compile(r"/[\w/\-\.]+"),                  # /unix/path
    re.compile(r"\b[\w]+/[\w/\-\.]+"),           # module/subpath
    re.compile(r"`([^`]+)`"),                    # `backtick quoted`
    re.compile(r'"([^"]+(?:\.\w{2,6}|/\w+))"'), # "quoted/path.ext"
]

# Constraint phrases
_CONSTRAINT_PATTERNS = re.compile(
    r"(?:don'?t|do not|without|avoid|never|no|except|excluding|"
    r"don'?t touch|leave|keep|preserve|maintain)\s+(.+?)(?:\.|,|$)",
    re.IGNORECASE,
)

# Success criteria phrases
_SUCCESS_CRITERIA_PATTERNS = re.compile(
    r"(?:until|so that|such that|should|must|expect|when done|"
    r"success|passes?|returns?|gives?|produces?|shows?|no longer|without error)\s+(.+?)(?:\.|,|$)",
    re.IGNORECASE,
)

# Action verbs that start the primary goal clause
_GOAL_VERB = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+|i need you to\s+|i want you to\s+)?"
    r"(fix|add|remove|update|delete|create|refactor|migrate|deploy|implement|write|"
    r"test|check|validate|build|replace|rename|move|convert|ensure|make|run|enable|"
    r"disable|patch|upgrade|revert|rollback|generate|debug|analyse|analyze|review)\b",
    re.IGNORECASE,
)

# Conjunction words that split goal from location
_GOAL_SPLIT = re.compile(r"\b(in|at|from|inside|within|under|for)\b", re.IGNORECASE)

# Pronoun resolution — last file mentioned pattern
_FILE_PATTERN = re.compile(r"[\w\-/]+\.\w{1,6}")


def _resolve_pronouns(task: str, conversation_history: list[str]) -> str:
    """Replace "it"/"this" with the last file/entity mentioned in history."""
    if not re.search(r"\b(it|this|that)\b", task, re.IGNORECASE):
        return task
    if not conversation_history:
        return task

    # Find the last file reference in history (most recent turn first)
    for turn in reversed(conversation_history):
        files = _FILE_PATTERN.findall(turn)
        if files:
            last_file = files[-1]
            task = re.sub(r"\b(it|this|that)\b", last_file, task, flags=re.IGNORECASE, count=1)
            return task
    return task


class IntentExtractor:
    """Extract structured intent from natural language task descriptions."""

    def extract(
        self,
        task: str,
        conversation_history: list[str] | None = None,
    ) -> StructuredIntent:
        """Parse a task description into StructuredIntent.

        Args:
            task: The natural language task.
            conversation_history: Prior conversation turns for context/pronoun resolution.

        Returns:
            StructuredIntent with goal, scope, constraints, success_criteria.
        """
        if not task or not task.strip():
            return StructuredIntent()

        history = conversation_history or []
        task = _resolve_pronouns(task.strip(), history)

        scope = self._extract_scope(task, history)
        constraints = self._extract_constraints(task)
        success_criteria = self._extract_success_criteria(task)
        goal = self._extract_goal(task, scope)
        specificity = self._compute_specificity(goal, scope, success_criteria, constraints)

        return StructuredIntent(
            goal=goal,
            scope=scope,
            constraints=constraints,
            success_criteria=success_criteria,
            specificity=specificity,
        )

    # ------------------------------------------------------------------
    # Extractors
    # ------------------------------------------------------------------

    def _extract_scope(self, task: str, history: list[str]) -> list[str]:
        """Extract file paths, module names, services from task + history."""
        found: set[str] = set()
        search_text = task + " " + " ".join(history[-3:])  # use recent history

        for pattern in _SCOPE_PATTERNS:
            for match in pattern.finditer(search_text):
                val = match.group(1) if match.lastindex else match.group(0)
                val = val.strip("\"'` ")
                # Filter out common false positives
                if (
                    len(val) > 2
                    and not re.match(r"^\d+(\.\d+)?$", val)  # not a number
                    and not re.match(r"^https?://", val)       # not a URL
                    and "://" not in val
                ):
                    found.add(val)

        return sorted(found)

    def _extract_constraints(self, task: str) -> list[str]:
        """Extract negative constraints (don't, avoid, without, etc.)."""
        constraints: list[str] = []
        for match in _CONSTRAINT_PATTERNS.finditer(task):
            constraint = match.group(1).strip()
            if constraint and len(constraint.split()) <= 12:
                constraints.append(constraint)
        return constraints[:5]  # cap at 5

    def _extract_success_criteria(self, task: str) -> list[str]:
        """Extract observable success conditions."""
        criteria: list[str] = []
        for match in _SUCCESS_CRITERIA_PATTERNS.finditer(task):
            criterion = match.group(1).strip()
            if criterion and len(criterion.split()) <= 15:
                criteria.append(criterion)
        return criteria[:5]

    def _extract_goal(self, task: str, scope: list[str]) -> str:
        """Extract the primary goal clause — verb + object, stripped of location."""
        # Find the start of the imperative
        m = _GOAL_VERB.search(task)
        if not m:
            # Fallback: take the first sentence, truncated
            first = re.split(r"[.!?\n]", task)[0]
            return first[:120].strip()

        goal_text = task[m.start():].strip()

        # Remove scope references from goal (they go into scope list)
        for item in scope:
            goal_text = goal_text.replace(item, "").strip()

        # Remove trailing location clauses ("in auth/middleware.py")
        goal_text = _GOAL_SPLIT.split(goal_text)[0].strip()

        # Clean up punctuation artifacts
        goal_text = re.sub(r"[,;:]+$", "", goal_text).strip()

        return goal_text[:120] if goal_text else task[:120]

    def _compute_specificity(
        self,
        goal: str,
        scope: list[str],
        success_criteria: list[str],
        constraints: list[str],
    ) -> float:
        """0.0–1.0 specificity score based on what was extracted."""
        score = 0.0
        if goal and len(goal.split()) >= 3:
            score += 0.30
        if scope:
            score += 0.30
        if success_criteria:
            score += 0.25
        if constraints:
            score += 0.10
        if len(goal.split()) >= 7:  # longer = more specific
            score += 0.05
        return round(min(1.0, score), 3)
