"""Core types and data structures for Sentigent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    """The five operational signals that drive agent judgment."""

    CAUTION = "caution"
    """Triggers validation on anomalies. Fires when observed values deviate
    significantly from learned baselines."""

    DOUBT = "doubt"
    """Seeks more information when confidence is low. Fires when compound
    confidence (agent + data quality) drops below threshold."""

    URGENCY = "urgency"
    """Reduces deliberation for time-sensitive actions. Fires when delay
    has measurable consequences."""

    CONFIDENCE = "confidence"
    """Enables fast-path for routine operations. Fires when patterns match
    known-good outcomes with high certainty."""

    FRUSTRATION = "frustration"
    """Triggers strategy change after repeated failures. Fires when retry
    count exceeds expectations."""


class Signal(BaseModel):
    """A computed operational signal with its strength and reasoning."""

    type: SignalType
    strength: float = Field(ge=0.0, le=1.0, description="Signal strength from 0 (absent) to 1 (maximum)")
    reason: str = Field(description="Human-readable explanation of why this signal fired")
    contributing_factors: list[str] = Field(default_factory=list, description="Specific factors that contributed to this signal")


class DecisionAction(str, Enum):
    """The four possible actions the judgment layer can recommend."""

    PROCEED = "proceed"
    """Let the agent continue. Signals indicate normal operation."""

    ENRICH = "enrich"
    """Gather more context before acting. Doubt or incomplete information detected."""

    SLOW_DOWN = "slow_down"
    """Add validation steps. Caution signal triggered but not severe enough to escalate."""

    ESCALATE = "escalate"
    """Route to human review. High caution/doubt or value hierarchy demands human judgment."""


class Decision(BaseModel):
    """The output of a Sentigent evaluation — the judgment call."""

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique ID for this decision trace, used for outcome attribution")
    action: DecisionAction = Field(description="Recommended action: proceed, enrich, slow_down, or escalate")
    reason: str = Field(description="Human-readable explanation of the judgment")
    signals: dict[str, float] = Field(default_factory=dict, description="All signal strengths: {'caution': 0.87, 'doubt': 0.45, ...}")
    signal_details: list[Signal] = Field(default_factory=list, description="Detailed signal information")
    judgment_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Current judgment accuracy score (improves over time)")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Sentigent's confidence in this specific decision")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context for debugging/audit")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Trace(BaseModel):
    """A complete decision trace — the full record of what happened."""

    trace_id: str
    agent_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task: str
    context: dict[str, Any] = Field(default_factory=dict)
    agent_state: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, float] = Field(default_factory=dict)
    decision: DecisionAction
    reason: str
    outcome: str | None = None
    outcome_timestamp: datetime | None = None
    outcome_feedback: str | None = None
    confidence_at_decision: float = 0.5


class ValueHierarchy(BaseModel):
    """Ordered list of values that guide decision-making.

    Higher-weighted values take priority when signals conflict.
    Example: safety (1.0) > speed (0.5) means caution overrides urgency.
    """

    values: list[tuple[str, float]] = Field(description="Ordered list of (value_name, weight) tuples. Weight 1.0 = non-negotiable.")

    def get_weight(self, value_name: str) -> float:
        """Get the weight for a named value, returns 0.0 if not found."""
        for name, weight in self.values:
            if name == value_name:
                return weight
        return 0.0

    def priority_order(self) -> list[str]:
        """Return value names sorted by weight (highest first)."""
        return [name for name, _ in sorted(self.values, key=lambda x: x[1], reverse=True)]


class BaselineStats(BaseModel):
    """Statistical baseline for a metric, learned from operational data."""

    metric_name: str
    median: float = 0.0
    mean: float = 0.0
    std: float = 1.0
    p5: float = 0.0
    p25: float = 0.0
    p75: float = 0.0
    p95: float = 0.0
    min_observed: float = 0.0
    max_observed: float = 0.0
    sample_size: int = 0
    source: str = "profile_default"  # "profile_default", "layer_1", "layer_2", "layer_3"
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def z_score(self, value: float) -> float:
        """Compute z-score of a value against this baseline."""
        if self.std == 0:
            return 0.0 if value == self.median else 10.0
        return abs(value - self.median) / self.std


class WorldModel(BaseModel):
    """Domain-specific baselines and expectations.

    Starts from profile defaults, progressively replaced by learned values.
    """

    baselines: dict[str, Any] = Field(default_factory=dict, description="Named baselines with statistical distributions or thresholds")
    baseline_stats: dict[str, BaselineStats] = Field(default_factory=dict, description="Computed statistical baselines from operational data")

    def get_baseline(self, metric_name: str) -> BaselineStats | None:
        """Get computed baseline stats for a metric."""
        return self.baseline_stats.get(metric_name)

    def update_baseline(self, metric_name: str, stats: BaselineStats) -> None:
        """Update a baseline with new computed statistics."""
        self.baseline_stats[metric_name] = stats


class Profile(BaseModel):
    """A domain profile — starter intuition for an agent.

    Provides day-1 baselines that get progressively replaced by learned judgment.
    Like training wheels that the agent outgrows.
    """

    name: str = Field(description="Profile name (e.g., 'financial_ops', 'customer_support')")
    description: str = Field(default="", description="What this profile is for")
    values: ValueHierarchy = Field(description="Priority ordering of values that guide decisions")
    world_model: WorldModel = Field(description="Domain-specific baselines and expectations")
    signal_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "caution_threshold": 2.0,  # z-score threshold
            "doubt_threshold": 0.6,  # compound confidence below this
            "urgency_threshold": 0.8,  # urgency score above this
            "confidence_fast_path": 0.9,  # confidence above this enables fast path
            "frustration_retries": 3,  # retries before frustration fires
        },
        description="Configurable thresholds for each signal type",
    )


# ── Task Context Layer (Phase 2) ──────────────────────────────────────────────

class TaskStatus(str, Enum):
    """Lifecycle states for a declared task."""
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class TaskContext(BaseModel):
    """A declared task — the unit of judgment for Phase 2.

    Agents declare a task before acting. Every subsequent evaluate() call
    is anchored to this task, enabling scope enforcement, constraint memory,
    and task-level outcome learning.
    """

    task_id: str = Field(description="Unique ID for this task session")
    goal: str = Field(description="What the agent is trying to accomplish")
    scope: list[str] = Field(
        default_factory=list,
        description="Files, services, or resources the agent is authorized to touch",
    )
    authorized_by: str = Field(
        default="user",
        description="Who authorized this task: 'user' | 'policy' | 'org_admin'",
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Observable signals that indicate task completion",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Explicit constraints: what the agent must NOT do",
    )
    status: TaskStatus = Field(default=TaskStatus.IN_PROGRESS)
    episode_count: int = Field(default=0, description="Number of evaluate() calls under this task")
    scope_violations: int = Field(default=0, description="Times an action fell outside declared scope")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_in_scope(self, target: str) -> bool | None:
        """Check if a target (file path, service name) is within declared scope.

        Returns None if scope is empty (no restriction declared).
        Returns True/False if scope is declared.
        """
        if not self.scope:
            return None  # no scope declared — unrestricted
        target_lower = target.lower()
        return any(s.lower() in target_lower or target_lower in s.lower() for s in self.scope)
