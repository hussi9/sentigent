"""SetupObserver — logs PostToolUse events to the setup observation window."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore

_SKIP_TOOLS = {
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch",
    "TaskList", "TaskGet", "TodoRead", "NotebookRead",
}


class SetupObserver:
    """Log PostToolUse events to the rolling setup observation window."""

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def observe(
        self,
        tool_name: str,
        tool_input: str,
        routing_confidence: float,
        exit_code: int | None = None,
    ) -> None:
        """Record one tool call observation.

        Args:
            tool_name: Name of the tool (e.g., "Bash", "Edit").
            tool_input: Input passed to the tool (first 500 chars stored).
            routing_confidence: Confidence score from sentigent_route for this call.
            exit_code: Process exit code (0=success, non-zero=failure, None=unknown).
        """
        if tool_name in _SKIP_TOOLS:
            return

        if exit_code is None:
            outcome_signal = "unknown"
        elif exit_code == 0:
            outcome_signal = "success"
        else:
            outcome_signal = "failure"

        self._store.log_setup_observation(
            tool_name=tool_name,
            tool_input=tool_input[:500],  # store enforces 500-char limit
            routing_confidence=routing_confidence,
            outcome_signal=outcome_signal,
        )

    def get_window(self, size: int = 50) -> list[dict[str, Any]]:
        """Return the most recent N observations from the rolling window."""
        return self._store.get_setup_observations(limit=size)
