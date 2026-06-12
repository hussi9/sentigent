"""Tests for DriftDetector — pure Python, no I/O."""
from __future__ import annotations
import pytest
from sentigent.setup.drift_detector import DriftDetector, DriftEvent


def _obs(tool_name="Bash", tool_input="cmd", routing_confidence=0.5, outcome_signal="success"):
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "routing_confidence": routing_confidence,
        "outcome_signal": outcome_signal,
    }


class TestRoutingDrift:
    def test_no_drift_when_confidence_is_high(self):
        observations = [_obs(routing_confidence=0.80) for _ in range(25)]
        events = DriftDetector().detect(observations)
        routing_events = [e for e in events if e.drift_type == "routing_confidence"]
        assert routing_events == []

    def test_detects_routing_drift_when_avg_confidence_low(self):
        observations = [_obs(routing_confidence=0.40) for _ in range(25)]
        events = DriftDetector().detect(observations)
        routing_events = [e for e in events if e.drift_type == "routing_confidence"]
        assert len(routing_events) == 1
        assert routing_events[0].severity in ("low", "medium", "high")

    def test_ignores_routing_drift_with_fewer_than_20_observations(self):
        observations = [_obs(routing_confidence=0.30) for _ in range(10)]
        events = DriftDetector().detect(observations)
        assert events == []


class TestMcpGapDetection:
    def test_detects_gh_cli_bash_pattern(self):
        observations = [
            _obs(tool_name="Bash", tool_input="gh pr create --title 'Fix X'"),
            _obs(tool_name="Bash", tool_input="gh issue list --state open"),
            _obs(tool_name="Bash", tool_input="gh pr merge 42 --squash"),
        ]
        events = DriftDetector().detect(observations)
        mcp_events = [e for e in events if e.drift_type == "mcp_gap"]
        assert len(mcp_events) == 1
        assert "github" in mcp_events[0].recommendation.lower()

    def test_no_mcp_gap_for_generic_bash(self):
        observations = [_obs(tool_name="Bash", tool_input="ls -la") for _ in range(5)]
        events = DriftDetector().detect(observations)
        assert [e for e in events if e.drift_type == "mcp_gap"] == []

    def test_requires_3_matching_calls_for_mcp_gap(self):
        observations = [
            _obs(tool_name="Bash", tool_input="gh pr create --title 'A'"),
            _obs(tool_name="Bash", tool_input="gh pr create --title 'B'"),
        ]
        events = DriftDetector().detect(observations)
        assert [e for e in events if e.drift_type == "mcp_gap"] == []


class TestDriftEventFields:
    def test_drift_event_has_required_fields(self):
        observations = [_obs(routing_confidence=0.35) for _ in range(25)]
        events = DriftDetector().detect(observations)
        assert len(events) > 0
        e = events[0]
        assert hasattr(e, "drift_type")
        assert hasattr(e, "severity")
        assert hasattr(e, "description")
        assert hasattr(e, "recommendation")
        assert hasattr(e, "suggested_change")
