"""Phase 4: Conversation Intelligence — Friction Detector.

Monitors conversation turns for patterns that indicate poor human-agent
interaction quality:

  1. Correction loops  — user rephrases or explicitly corrects the agent 2+ times
  2. Scope rejections  — agent acts outside declared scope, user pushes back 2+ times
  3. Frustration markers — explicit frustration language in user turns
  4. Repeated clarification — agent asks the same clarification question multiple times

FrictionEvent is pure observation — it does not make decisions.
The Session Health Monitor aggregates events into an actionable health score.

Usage::

    from sentigent.core.friction_detector import FrictionDetector

    detector = FrictionDetector()
    events = detector.analyze(turns)
    summary = detector.session_summary(events)
    # summary["friction_events"] → 3
    # summary["level"] → "moderate"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple


class FrictionType(str, Enum):
    CORRECTION_LOOP = "correction_loop"
    """User explicitly corrects the agent or rephrases the same task."""

    SCOPE_REJECTION = "scope_rejection"
    """User rejects agent output as out-of-scope or wrong area."""

    FRUSTRATION_MARKER = "frustration_marker"
    """Explicit frustration language in user turn."""

    REPEATED_CLARIFICATION = "repeated_clarification"
    """Agent asks the same clarifying question more than once."""

    CONTRADICTION = "contradiction"
    """User instruction contradicts a prior instruction in the same session."""


class FrictionLevel(str, Enum):
    NONE = "none"       # 0 events
    LOW = "low"         # 1 event
    MODERATE = "moderate"  # 2–3 events
    HIGH = "high"       # 4+ events


@dataclass
class FrictionEvent:
    """A single detected friction event in the conversation."""

    type: FrictionType
    turn_index: int
    description: str
    snippet: str        # the actual text fragment that triggered detection
    intervention: str   # suggested action to improve the conversation


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

# Explicit correction signals
_CORRECTION_PATTERNS = re.compile(
    r"\b(no[,.]?\s|not quite|that'?s? (wrong|not right|incorrect|not what|not it)|"
    r"actually[,]?\s|i meant|i said|you misunderstood|you missed|wrong file|"
    r"wrong function|wrong class|not that|that'?s? not|please re-?read|"
    r"read again|as i said|like i said|i already said|i already told)\b",
    re.IGNORECASE,
)

# Scope rejection signals
_SCOPE_REJECTION_PATTERNS = re.compile(
    r"\b(out of scope|not in scope|don'?t touch|leave that|don'?t change that|"
    r"only (change|fix|update|modify)|not (that|this|those)|wrong (area|place|file|service)|"
    r"stay in|stick to|focus on|i (only|just) want(ed)? you to)\b",
    re.IGNORECASE,
)

# Frustration markers
_FRUSTRATION_PATTERNS = re.compile(
    r"\b(ugh|argh|come on|seriously|why (can'?t|won'?t|don'?t)|this is (wrong|broken|terrible|"
    r"awful|ridiculous|stupid)|you keep|stop doing|i keep (saying|telling)|"
    r"how (many|many more) times|again\?|seriously\?|unbelievable|wtf|what the)\b",
    re.IGNORECASE,
)

# Agent clarification question patterns (detect repeated questions)
_CLARIFICATION_PATTERNS = re.compile(
    r"\b(which (file|function|service|class|module|method)|"
    r"what (file|function|service|do you mean|do you want|should)|"
    r"can you (clarify|specify|elaborate)|could you (clarify|specify)|"
    r"what do you mean by|what exactly)\b",
    re.IGNORECASE,
)

# Contradiction detection — "do X" followed by "don't do X" or "undo X"
_CONTRADICTION_PAIRS = [
    (re.compile(r"\b(add|create|implement|enable)\b", re.IGNORECASE),
     re.compile(r"\b(remove|delete|disable|revert)\b", re.IGNORECASE)),
    (re.compile(r"\b(keep|maintain|preserve)\b", re.IGNORECASE),
     re.compile(r"\b(remove|change|replace|delete)\b", re.IGNORECASE)),
]


class FrictionDetector:
    """Detect friction events in a conversation session."""

    def analyze(self, turns: list[str]) -> list[FrictionEvent]:
        """Analyze conversation turns for friction events.

        Args:
            turns: Alternating user/agent turns. Even indices = user, odd = agent.
                   (Or mixed — the detector treats all turns as potential sources.)

        Returns:
            List of FrictionEvent, in turn order.
        """
        if not turns:
            return []

        events: list[FrictionEvent] = []

        correction_count = 0
        scope_rejection_count = 0
        clarification_fingerprints: list[str] = []

        for i, turn in enumerate(turns):
            if not turn or not turn.strip():
                continue

            # Correction loop detection
            if _CORRECTION_PATTERNS.search(turn):
                correction_count += 1
                if correction_count >= 2:
                    snippet = _CORRECTION_PATTERNS.search(turn).group(0)  # type: ignore[union-attr]
                    events.append(FrictionEvent(
                        type=FrictionType.CORRECTION_LOOP,
                        turn_index=i,
                        description=f"Correction loop detected (occurrence {correction_count})",
                        snippet=snippet,
                        intervention=(
                            "Agent should re-read the original task and declared scope "
                            "before continuing. Consider calling sentigent_active_tasks()."
                        ),
                    ))

            # Scope rejection
            if _SCOPE_REJECTION_PATTERNS.search(turn):
                scope_rejection_count += 1
                if scope_rejection_count >= 2:
                    snippet = _SCOPE_REJECTION_PATTERNS.search(turn).group(0)  # type: ignore[union-attr]
                    events.append(FrictionEvent(
                        type=FrictionType.SCOPE_REJECTION,
                        turn_index=i,
                        description=f"Scope rejection #{scope_rejection_count}",
                        snippet=snippet,
                        intervention=(
                            "Task scope is unclear or agent is drifting. "
                            "Re-declare the task with explicit scope constraints via sentigent_start_task()."
                        ),
                    ))

            # Frustration marker
            m = _FRUSTRATION_PATTERNS.search(turn)
            if m:
                events.append(FrictionEvent(
                    type=FrictionType.FRUSTRATION_MARKER,
                    turn_index=i,
                    description="User frustration detected",
                    snippet=m.group(0),
                    intervention=(
                        "Stop and acknowledge the frustration. Summarize what the agent "
                        "understood and ask the user to confirm before continuing."
                    ),
                ))

            # Repeated clarification
            m_clar = _CLARIFICATION_PATTERNS.search(turn)
            if m_clar:
                fingerprint = m_clar.group(0).lower()
                if fingerprint in clarification_fingerprints:
                    events.append(FrictionEvent(
                        type=FrictionType.REPEATED_CLARIFICATION,
                        turn_index=i,
                        description=f"Agent repeated clarification question: '{fingerprint}'",
                        snippet=m_clar.group(0),
                        intervention=(
                            "The agent is stuck in a clarification loop. "
                            "Provide a best-effort interpretation and state assumptions explicitly."
                        ),
                    ))
                else:
                    clarification_fingerprints.append(fingerprint)

        # Contradiction detection (cross-turn)
        events.extend(self._detect_contradictions(turns))

        # Sort by turn_index
        events.sort(key=lambda e: e.turn_index)
        return events

    def _detect_contradictions(self, turns: list[str]) -> list[FrictionEvent]:
        """Detect instruction contradictions across turns."""
        events: list[FrictionEvent] = []
        for i in range(1, len(turns)):
            for add_pattern, remove_pattern in _CONTRADICTION_PAIRS:
                prev_turns_text = " ".join(turns[:i])
                if add_pattern.search(prev_turns_text) and remove_pattern.search(turns[i]):
                    # Check they're talking about the same noun
                    prev_nouns = set(re.findall(r"\b[A-Za-z]{4,}\b", prev_turns_text))
                    cur_nouns = set(re.findall(r"\b[A-Za-z]{4,}\b", turns[i]))
                    if len(prev_nouns & cur_nouns) >= 2:
                        events.append(FrictionEvent(
                            type=FrictionType.CONTRADICTION,
                            turn_index=i,
                            description="Possible instruction contradiction detected",
                            snippet=turns[i][:80],
                            intervention=(
                                "Clarify which instruction takes precedence before proceeding."
                            ),
                        ))
                        break  # one contradiction per turn is enough
        return events

    def session_summary(self, events: list[FrictionEvent]) -> dict:
        """Aggregate friction events into a session summary.

        Returns:
            {
                "friction_events": int,
                "level": "none" | "low" | "moderate" | "high",
                "by_type": {FrictionType: count},
                "friction_absence_score": float,  # 1.0 = no friction, 0.0 = very high
                "top_intervention": str,
            }
        """
        count = len(events)

        if count == 0:
            level = FrictionLevel.NONE
        elif count == 1:
            level = FrictionLevel.LOW
        elif count <= 3:
            level = FrictionLevel.MODERATE
        else:
            level = FrictionLevel.HIGH

        by_type: dict[str, int] = {}
        for ev in events:
            by_type[ev.type.value] = by_type.get(ev.type.value, 0) + 1

        # friction_absence_score: 1.0 = zero friction, decays with events
        friction_absence = max(0.0, 1.0 - count * 0.2)

        top_intervention = ""
        if events:
            # Prioritise frustration and correction loops
            priority_order = [
                FrictionType.FRUSTRATION_MARKER,
                FrictionType.CORRECTION_LOOP,
                FrictionType.SCOPE_REJECTION,
                FrictionType.REPEATED_CLARIFICATION,
                FrictionType.CONTRADICTION,
            ]
            for ft in priority_order:
                for ev in events:
                    if ev.type == ft:
                        top_intervention = ev.intervention
                        break
                if top_intervention:
                    break

        return {
            "friction_events": count,
            "level": level.value,
            "by_type": by_type,
            "friction_absence_score": round(friction_absence, 3),
            "top_intervention": top_intervention,
        }
