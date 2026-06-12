"""Behavior Modulator / Decision Gate — decides what action to take based on signals and values.

The gate receives computed signals and the value hierarchy, then determines:
- PROCEED: let the agent continue normally
- ENRICH: gather more context before acting
- SLOW_DOWN: add validation steps
- ESCALATE: route to human review

The gate also considers the interplay between signals. For example, high urgency
can override moderate caution, but high caution always overrides urgency if the
value hierarchy says safety > speed.

Session memory: The gate tracks its own decisions within a session so it can:
- Remember that a context was already escalated and human-approved
- Accumulate risk across sequential evaluations
- Avoid repeatedly blocking the same approved operation
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import logging

from sentigent.core.types import (
    DecisionAction,
    Profile,
    Signal,
    SignalType,
)
from sentigent.observability import structured_log

gate_logger = logging.getLogger("sentigent.gate")


@dataclass
class SessionDecision:
    """A record of a decision made during the current session."""

    trace_id: str
    action: DecisionAction
    signals: dict[str, float]
    task_summary: str
    timestamp: float = field(default_factory=time.time)
    human_approved: bool = False


class SessionContext:
    """Tracks decision history within a session for context-aware gating.

    Maintains a sliding window of recent decisions so the gate can:
    - Skip re-escalation for human-approved contexts
    - Track cumulative risk across a session
    - Adapt its sensitivity based on recent decision patterns
    """

    def __init__(self, max_history: int = 200) -> None:
        self._decisions: deque[SessionDecision] = deque(maxlen=max_history)
        self._approved_contexts: dict[str, float] = {}  # task_hash -> approval_time

    def record_decision(
        self,
        trace_id: str,
        action: DecisionAction,
        signals: dict[str, float],
        task_summary: str,
    ) -> None:
        """Record a decision made during this session."""
        self._decisions.append(SessionDecision(
            trace_id=trace_id,
            action=action,
            signals=signals,
            task_summary=task_summary,
        ))

    def record_approval(self, task_summary: str) -> None:
        """Record that a human approved an escalated decision."""
        key = self._hash_task(task_summary)
        self._approved_contexts[key] = time.time()

    def was_recently_approved(self, task_summary: str, window_seconds: float = 300) -> bool:
        """Check if a similar context was recently approved by a human."""
        key = self._hash_task(task_summary)
        approval_time = self._approved_contexts.get(key)
        if approval_time is None:
            return False
        return (time.time() - approval_time) < window_seconds

    @property
    def recent_escalation_count(self) -> int:
        """Count escalations in the last 10 decisions."""
        recent = list(self._decisions)[-10:]
        return sum(1 for d in recent if d.action == DecisionAction.ESCALATE)

    @property
    def cumulative_risk(self) -> float:
        """Compute cumulative risk from recent decisions (0.0 to 1.0).

        Tracks how much caution has accumulated in the session. High cumulative
        risk makes the gate more conservative.
        """
        recent = list(self._decisions)[-20:]
        if not recent:
            return 0.0

        total_caution = sum(d.signals.get("caution", 0) for d in recent)
        return min(1.0, total_caution / max(len(recent), 1))

    @staticmethod
    def _hash_task(task_summary: str) -> str:
        """Create a simple hash for task context matching."""
        normalized = task_summary.lower().strip()[:100]
        return normalized


class DecisionGate:
    """Determines the appropriate action based on signals and value hierarchy.

    The gate is the final decision maker. It takes the computed signals and
    applies the domain's value hierarchy to produce an action recommendation.

    Maintains session context to avoid redundant escalations and track risk.
    """

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.values = profile.values
        self.session = SessionContext()

    def decide(
        self,
        signals: list[Signal],
        task_summary: str = "",
    ) -> tuple[DecisionAction, str]:
        """Given computed signals, determine the appropriate action.

        Args:
            signals: List of computed signals from the Signal Engine
            task_summary: Optional task description for session memory

        Returns:
            Tuple of (action, reason) explaining the decision
        """
        signal_map = {s.type: s for s in signals}
        caution = signal_map.get(SignalType.CAUTION)
        doubt = signal_map.get(SignalType.DOUBT)
        urgency = signal_map.get(SignalType.URGENCY)
        confidence = signal_map.get(SignalType.CONFIDENCE)
        frustration = signal_map.get(SignalType.FRUSTRATION)

        caution_strength = caution.strength if caution else 0.0
        doubt_strength = doubt.strength if doubt else 0.0
        urgency_strength = urgency.strength if urgency else 0.0
        confidence_strength = confidence.strength if confidence else 0.0
        frustration_strength = frustration.strength if frustration else 0.0

        reasons: list[str] = []

        # Session context check: if this was already escalated and human-approved, proceed
        if task_summary and self.session.was_recently_approved(task_summary):
            reasons.append("Previously escalated and human-approved in this session")
            action = DecisionAction.PROCEED
            self._record_session_decision(signals, action, task_summary)
            return action, "; ".join(reasons)

        # Cumulative risk: if session has accumulated high risk, be more conservative
        cumulative_risk = self.session.cumulative_risk
        if cumulative_risk > 0.5 and caution_strength > 0.3:
            caution_strength = min(1.0, caution_strength + cumulative_risk * 0.2)

        # Rule 1: Frustration overrides everything — escalate for strategy change
        if frustration_strength > 0.7:
            reasons.append(f"Frustration signal high ({frustration_strength:.2f})")
            if frustration:
                reasons.extend(frustration.contributing_factors)
            action = DecisionAction.ESCALATE
            self._record_session_decision(signals, action, task_summary)
            return action, "; ".join(reasons)

        # Rule 2: High caution — check value hierarchy
        if caution_strength > 0.7:
            safety_weight = self.values.get_weight("safety") or self.values.get_weight("financial_safety")
            speed_weight = self.values.get_weight("speed") or self.values.get_weight("task_completion_speed")

            if safety_weight > speed_weight or speed_weight == 0:
                reasons.append(f"Caution signal high ({caution_strength:.2f})")
                if caution:
                    reasons.extend(caution.contributing_factors)
                reasons.append(f"Value hierarchy: safety ({safety_weight}) > speed ({speed_weight})")
                action = DecisionAction.ESCALATE
                self._record_session_decision(signals, action, task_summary)
                return action, "; ".join(reasons)
            else:
                if urgency_strength > 0.7:
                    reasons.append(f"Caution ({caution_strength:.2f}) tempered by urgency ({urgency_strength:.2f})")
                    action = DecisionAction.SLOW_DOWN
                    self._record_session_decision(signals, action, task_summary)
                    return action, "; ".join(reasons)
                else:
                    reasons.append(f"Caution signal high ({caution_strength:.2f})")
                    if caution:
                        reasons.extend(caution.contributing_factors)
                    action = DecisionAction.ESCALATE
                    self._record_session_decision(signals, action, task_summary)
                    return action, "; ".join(reasons)

        # Rule 3: Moderate caution — slow down
        if caution_strength > 0.4:
            reasons.append(f"Moderate caution ({caution_strength:.2f})")
            if caution:
                reasons.extend(caution.contributing_factors)
            action = DecisionAction.SLOW_DOWN
            self._record_session_decision(signals, action, task_summary)
            return action, "; ".join(reasons)

        # Rule 4: Doubt present — enrich with more context
        if doubt_strength > 0.4:
            reasons.append(f"Doubt signal active ({doubt_strength:.2f})")
            if doubt:
                reasons.extend(doubt.contributing_factors)
            action = DecisionAction.ENRICH
            self._record_session_decision(signals, action, task_summary)
            return action, "; ".join(reasons)

        # Rule 5: High confidence — fast path
        if confidence_strength > 0.9:
            reasons.append(f"High confidence ({confidence_strength:.2f}), fast-path enabled")
            if confidence:
                reasons.extend(confidence.contributing_factors)
            action = DecisionAction.PROCEED
            self._record_session_decision(signals, action, task_summary)
            return action, "; ".join(reasons)

        # Rule 6: Default — proceed with standard checks
        reasons.append("All signals within normal range")
        action = DecisionAction.PROCEED
        self._record_session_decision(signals, action, task_summary)
        return action, "; ".join(reasons)

    def _record_session_decision(
        self,
        signals: list[Signal],
        action: DecisionAction,
        task_summary: str,
    ) -> None:
        """Record the decision in session context."""
        signal_strengths = {s.type.value: s.strength for s in signals}
        self.session.record_decision(
            trace_id="",
            action=action,
            signals=signal_strengths,
            task_summary=task_summary,
        )

        # Structured log for non-PROCEED decisions (interventions worth tracking)
        if action != DecisionAction.PROCEED:
            structured_log(
                gate_logger, logging.INFO, "gate_intervention",
                action=action.value,
                cumulative_risk=round(self.session.cumulative_risk, 3),
                recent_escalations=self.session.recent_escalation_count,
                caution=signal_strengths.get("caution", 0),
                doubt=signal_strengths.get("doubt", 0),
                task=task_summary[:80] if task_summary else "",
            )
