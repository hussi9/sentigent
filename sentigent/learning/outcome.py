"""Outcome attribution — links outcomes to decisions for learning.

Four attribution sources (all needed for robust learning):
1. Explicit human feedback — "this escalation was correct/unnecessary"
2. Downstream signals — refund later flagged as fraud → escalation was correct
3. Absence of complaints — no issue within 48hrs → probably fine
4. LLM-as-judge — model evaluates decision quality after the fact

This module provides utilities for each attribution method.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sentigent.core.types import Trace


class OutcomeAttributor:
    """Manages outcome attribution for decision traces.

    Determines whether past decisions were correct based on multiple
    signals: explicit feedback, downstream events, and time-based inference.
    """

    def __init__(
        self,
        absence_window_hours: int = 48,
        auto_correct_confidence: float = 0.7,
    ) -> None:
        """
        Args:
            absence_window_hours: Hours without complaint before inferring "correct"
            auto_correct_confidence: Minimum confidence to auto-attribute "correct"
                                     for absence-based attribution
        """
        self.absence_window = timedelta(hours=absence_window_hours)
        self.auto_correct_confidence = auto_correct_confidence

    def attribute_from_feedback(
        self,
        trace_id: str,
        outcome: str,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Attribute outcome from explicit human feedback.

        This is the highest-confidence attribution source.

        Args:
            trace_id: The decision trace to attribute
            outcome: "correct", "incorrect", or "neutral"
            feedback: Optional explanation

        Returns:
            Attribution record
        """
        return {
            "trace_id": trace_id,
            "outcome": outcome,
            "source": "human_feedback",
            "confidence": 1.0,
            "feedback": feedback,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def attribute_from_downstream(
        self,
        trace_id: str,
        downstream_event: str,
        event_indicates: str,
        confidence: float = 0.85,
    ) -> dict[str, Any]:
        """Attribute outcome from a downstream event.

        Example: A refund was later flagged as fraud → the escalation decision was correct.

        Args:
            trace_id: The decision trace to attribute
            downstream_event: Description of the event
            event_indicates: "correct" or "incorrect"
            confidence: How confident we are in this attribution

        Returns:
            Attribution record
        """
        return {
            "trace_id": trace_id,
            "outcome": event_indicates,
            "source": "downstream_event",
            "confidence": confidence,
            "event": downstream_event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def check_absence_attribution(
        self,
        trace: Trace,
        current_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Check if enough time has passed to infer "correct" from absence of complaints.

        If a decision was made and no negative outcome was reported within
        the absence window, we can tentatively attribute it as "correct"
        (with lower confidence than explicit feedback).

        Args:
            trace: The decision trace to check
            current_time: Current time (defaults to now)

        Returns:
            Attribution record if window has passed, None otherwise
        """
        if trace.outcome is not None:
            return None  # Already has an outcome

        now = current_time or datetime.now(timezone.utc)
        elapsed = now - trace.timestamp

        if elapsed < self.absence_window:
            return None  # Not enough time has passed

        # Only auto-attribute if the original decision had reasonable confidence
        if trace.confidence_at_decision < self.auto_correct_confidence:
            return None  # Too uncertain to auto-attribute

        # Phase 0 honest-foundation: absence of a complaint is NOT evidence the
        # decision was right — it is the absence of evidence. Mark 'neutral'
        # (excluded from judgment_score and rule-mining) instead of fabricating
        # a 'correct'. Real positive signal comes from decision_events
        # (approve/keep) or the Gemma outcome-labeler, never from silence.
        # See docs/plans/2026-06-03-operator-autopilot-design.md (G1).
        return {
            "trace_id": trace.trace_id,
            "outcome": "neutral",
            "source": "absence_inference",
            "confidence": 0.0,
            "reason": f"No outcome signal after {self.absence_window.total_seconds() / 3600:.0f}h (absence != correct)",
            "timestamp": now.isoformat(),
        }
