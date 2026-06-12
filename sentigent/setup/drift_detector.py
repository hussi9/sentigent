"""DriftDetector — detects two classes of configuration drift from observations.

Pure Python. Takes a list of observation dicts (from SetupObserver.get_window())
and returns DriftEvent objects. No database I/O.

Drift classes:
  routing_confidence — average routing confidence below threshold over last N calls
  mcp_gap            — repeated bash sequences that match a known MCP tool pattern
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_ROUTING_DRIFT_THRESHOLD = 0.55
_ROUTING_MIN_OBSERVATIONS = 20
_MCP_GAP_MIN_MATCHES = 3

_MCP_FINGERPRINTS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"\bgh\s+(pr|issue|repo|release|workflow)\b", re.IGNORECASE),
        "GitHub MCP",
        "Use the GitHub MCP server instead of gh CLI to save ~4 tool calls per operation.",
    ),
    (
        re.compile(r"\b(curl|wget)\s+.*https?://", re.IGNORECASE),
        "HTTP/Fetch MCP",
        "Use the fetch MCP tool for HTTP requests instead of curl/wget.",
    ),
    (
        re.compile(r"\bpsql\s+-c\b|\bsqlite3\s+", re.IGNORECASE),
        "Database MCP",
        "Use a database MCP server to query your DB with structured tool calls.",
    ),
    (
        re.compile(r"\bplaywright\b|\bpuppeteer\b|\bselenium\b", re.IGNORECASE),
        "Playwright MCP",
        "Use the Playwright MCP server for browser automation tool calls.",
    ),
]


@dataclass
class DriftEvent:
    """A single detected drift signal."""

    drift_type: str
    severity: str
    description: str
    recommendation: str
    suggested_change: dict[str, Any] = field(default_factory=dict)


class DriftDetector:
    """Detect configuration drift from a window of tool call observations."""

    def detect(self, observations: list[dict[str, Any]]) -> list[DriftEvent]:
        if not observations:
            return []
        events: list[DriftEvent] = []
        events.extend(self._check_routing_confidence(observations))
        events.extend(self._check_mcp_gaps(observations))
        return events

    def _check_routing_confidence(self, observations: list[dict[str, Any]]) -> list[DriftEvent]:
        confidences = [
            float(obs.get("routing_confidence", 0.0))
            for obs in observations
            if obs.get("routing_confidence") is not None
        ]
        if len(confidences) < _ROUTING_MIN_OBSERVATIONS:
            return []
        avg = sum(confidences) / len(confidences)
        if avg >= _ROUTING_DRIFT_THRESHOLD:
            return []
        severity = "high" if avg < 0.40 else "medium" if avg < 0.48 else "low"
        return [DriftEvent(
            drift_type="routing_confidence",
            severity=severity,
            description=(
                f"Average routing confidence is {avg:.2f} (threshold: {_ROUTING_DRIFT_THRESHOLD}). "
                "Routing seeds may be stale or missing for recent task types."
            ),
            recommendation=(
                "Refresh routing seeds by running `sentigent_learn_now()` or adding seeds "
                "for recently common task types."
            ),
            suggested_change={
                "action": "refresh_routing_seeds",
                "current_avg_confidence": round(avg, 3),
                "target_threshold": _ROUTING_DRIFT_THRESHOLD,
            },
        )]

    def _check_mcp_gaps(self, observations: list[dict[str, Any]]) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        bash_inputs = [
            obs.get("tool_input", "")
            for obs in observations
            if (obs.get("tool_name") or "").lower() == "bash"
        ]
        for pattern, mcp_name, recommendation in _MCP_FINGERPRINTS:
            matches = [inp for inp in bash_inputs if pattern.search(inp)]
            if len(matches) >= _MCP_GAP_MIN_MATCHES:
                events.append(DriftEvent(
                    drift_type="mcp_gap",
                    severity="medium",
                    description=(
                        f"Detected {len(matches)} bash calls matching {mcp_name} patterns "
                        f"in the last {len(observations)} tool calls."
                    ),
                    recommendation=f"{mcp_name}: {recommendation}",
                    suggested_change={
                        "action": "recommend_mcp",
                        "mcp_name": mcp_name,
                        "matched_count": len(matches),
                    },
                ))
        return events
