"""Tests for the dashboard module (terminal + web)."""

import json
import os
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import pytest

from sentigent.config import SentigentConfig, set_config
from sentigent.core.types import DecisionAction, Trace
from sentigent.dashboard import (
    DashboardHandler,
    _get_dashboard_data,
    _get_store,
    _query_daily_activity,
    _query_decision_distribution,
    _query_impact_metrics,
    _query_recent_episodes,
    _query_rules,
    _query_tool_stats,
    cmd_dashboard,
    cmd_web,
)
from sentigent.memory.store import MemoryStore


@pytest.fixture
def db_path():
    """Create a temp database path."""
    path = os.path.join(tempfile.gettempdir(), "test_dashboard.db")
    if os.path.exists(path):
        os.remove(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def store(db_path: str) -> MemoryStore:
    """Create a MemoryStore with some test data."""
    s = MemoryStore(agent_id="test_agent", org_id="test_org", db_path=db_path)

    # Add episodes with various decisions and outcomes
    decisions = [
        ("task-1", "Bash: rm -rf /tmp/test", DecisionAction.PROCEED, 0.9, "correct"),
        ("task-2", "Write: config.py", DecisionAction.PROCEED, 0.85, "correct"),
        ("task-3", "Bash: git push --force", DecisionAction.ESCALATE, 0.4, "correct"),
        ("task-4", "Edit: .env.production", DecisionAction.ESCALATE, 0.3, "correct"),
        ("task-5", "Bash: npm install", DecisionAction.PROCEED, 0.95, "correct"),
        ("task-6", "Write: main.py", DecisionAction.SLOW_DOWN, 0.6, "incorrect"),
        ("task-7", "Bash: docker build", DecisionAction.PROCEED, 0.88, None),
        ("task-8", "Edit: utils.ts", DecisionAction.ENRICH, 0.5, "correct"),
    ]

    for trace_id, task, decision, conf, outcome in decisions:
        trace = Trace(
            trace_id=trace_id,
            agent_id="test_agent",
            task=task,
            context={"tool": task.split(":")[0]},
            signals={"caution": 1 - conf},
            decision=decision,
            reason=f"Test decision for {task}",
            confidence_at_decision=conf,
        )
        s.store_episode(trace)
        if outcome:
            s.record_outcome(trace_id, outcome)

    return s


@pytest.fixture
def configured_store(store: MemoryStore, db_path: str):
    """Set up global config pointing to our test store."""
    config = SentigentConfig(
        agent_id="test_agent",
        org_id="test_org",
        db_path=db_path,
    )
    set_config(config)
    yield store
    set_config(None)  # type: ignore[arg-type]


class TestQueryFunctions:

    def test_query_recent_episodes(self, store: MemoryStore, db_path: str):
        """Should return recent episodes sorted by timestamp desc."""
        result = _query_recent_episodes(db_path, "test_agent", limit=5)
        assert len(result) == 5
        assert all("trace_id" in ep for ep in result)
        assert all("decision" in ep for ep in result)
        assert all("confidence" in ep for ep in result)

    def test_query_recent_episodes_truncates_task(self, store: MemoryStore, db_path: str):
        """Task strings should be truncated to 80 chars."""
        result = _query_recent_episodes(db_path, "test_agent")
        for ep in result:
            assert len(ep["task"]) <= 80

    def test_query_decision_distribution(self, store: MemoryStore, db_path: str):
        """Should return counts per decision type."""
        result = _query_decision_distribution(db_path, "test_agent")
        assert isinstance(result, dict)
        assert "proceed" in result
        assert "escalate" in result
        assert result["proceed"] == 4  # 4 proceed decisions
        assert result["escalate"] == 2

    def test_query_daily_activity(self, store: MemoryStore, db_path: str):
        """Should return daily aggregation."""
        result = _query_daily_activity(db_path, "test_agent", days=7)
        assert isinstance(result, list)
        # All episodes are from today
        if result:
            assert result[0]["total"] > 0
            assert "correct" in result[0]
            assert "incorrect" in result[0]

    def test_query_tool_stats(self, store: MemoryStore, db_path: str):
        """Should return per-tool statistics."""
        result = _query_tool_stats(db_path, "test_agent")
        assert isinstance(result, list)
        assert len(result) > 0
        first = result[0]
        assert "tool" in first
        assert "count" in first
        assert "avg_confidence" in first

    def test_query_rules_empty(self, store: MemoryStore, db_path: str):
        """Should return empty list when no rules exist."""
        result = _query_rules(db_path, "test_agent")
        assert result == []

    def test_query_nonexistent_agent(self, db_path: str):
        """Queries for nonexistent agent return empty results."""
        # Create DB first
        MemoryStore(agent_id="other", org_id="org", db_path=db_path)
        result = _query_recent_episodes(db_path, "nonexistent")
        assert result == []


class TestImpactMetrics:

    def test_disasters_prevented(self, store: MemoryStore, db_path: str):
        """Should count escalate/slow_down decisions with correct outcome."""
        result = _query_impact_metrics(db_path, "test_agent")
        # From test data: task-3 (escalate, correct) + task-4 (escalate, correct) = 2
        # task-6 (slow_down, incorrect) doesn't count
        assert result["disasters_prevented"] == 2

    def test_risk_interventions(self, store: MemoryStore, db_path: str):
        """Should count all non-proceed decisions."""
        result = _query_impact_metrics(db_path, "test_agent")
        # escalate: task-3, task-4; slow_down: task-6; enrich: task-8 = 4
        assert result["risk_interventions"] == 4

    def test_enrichments_helped(self, store: MemoryStore, db_path: str):
        """Should count enrich decisions with correct outcome."""
        result = _query_impact_metrics(db_path, "test_agent")
        # task-8: enrich + correct = 1
        assert result["enrichments_helped"] == 1

    def test_mistakes_slipped(self, store: MemoryStore, db_path: str):
        """Should count proceed decisions with incorrect outcome."""
        result = _query_impact_metrics(db_path, "test_agent")
        # No proceed+incorrect in test data
        assert result["mistakes_slipped"] == 0

    def test_correct_streak(self, store: MemoryStore, db_path: str):
        """Should count consecutive correct from most recent."""
        result = _query_impact_metrics(db_path, "test_agent")
        # Most recent with outcomes: depends on insertion order
        # All were inserted sequentially, task-8 last (correct), task-7 has no outcome,
        # task-6 (incorrect) breaks streak — so streak = 1 (just task-8)
        assert result["correct_streak"] >= 1

    def test_score_trend_with_enough_data(self, store: MemoryStore, db_path: str):
        """Score trend should exist when >= 10 outcomes."""
        result = _query_impact_metrics(db_path, "test_agent")
        # Only 7 outcomes in test data — not enough for trend
        assert result["score_trend"] is None

    def test_score_trend_with_many_outcomes(self, db_path: str):
        """Score trend should show improvement data when enough outcomes."""
        s = MemoryStore(agent_id="trend_agent", org_id="test_org", db_path=db_path)
        # Create 20 episodes: first 10 mixed, second 10 all correct
        for i in range(20):
            trace = Trace(
                trace_id=f"trend-{i}",
                agent_id="trend_agent",
                task=f"Action {i}",
                context={},
                signals={},
                decision=DecisionAction.PROCEED,
                reason="test",
                confidence_at_decision=0.9,
            )
            s.store_episode(trace)
            outcome = "incorrect" if i < 5 else "correct"
            s.record_outcome(f"trend-{i}", outcome)

        result = _query_impact_metrics(db_path, "trend_agent")
        assert result["score_trend"] is not None
        assert result["score_trend"]["improving"] is True
        assert result["score_trend"]["second_half_score"] > result["score_trend"]["first_half_score"]

    def test_rules_and_baselines_count(self, store: MemoryStore, db_path: str):
        """Should count rules and baselines (0 for fresh store)."""
        result = _query_impact_metrics(db_path, "test_agent")
        assert result["rules_learned"] >= 0
        assert result["baselines_formed"] >= 0

    def test_empty_agent(self, db_path: str):
        """Impact metrics for empty agent should all be zero."""
        MemoryStore(agent_id="empty", org_id="org", db_path=db_path)
        result = _query_impact_metrics(db_path, "empty")
        assert result["disasters_prevented"] == 0
        assert result["risk_interventions"] == 0
        assert result["correct_streak"] == 0
        assert result["score_trend"] is None


class TestGetDashboardData:

    def test_returns_all_sections(self, configured_store):
        """Dashboard data should contain all expected keys."""
        data = _get_dashboard_data()
        assert "config" in data
        assert "summary" in data
        assert "baselines" in data
        assert "decision_distribution" in data
        assert "daily_activity" in data
        assert "tool_stats" in data
        assert "recent_episodes" in data
        assert "rules" in data
        assert "impact" in data
        assert "generated_at" in data

    def test_summary_has_correct_counts(self, configured_store):
        """Summary should reflect the test data."""
        data = _get_dashboard_data()
        s = data["summary"]
        assert s["total_episodes"] == 8
        assert s["total_with_outcomes"] == 7  # 7 have outcomes
        assert s["correct_count"] == 6  # 6 correct
        assert s["judgment_score"] == pytest.approx(6 / 7, abs=0.01)

    def test_config_reflects_settings(self, configured_store):
        """Config section should match what we set."""
        data = _get_dashboard_data()
        assert data["config"]["agent_id"] == "test_agent"
        assert data["config"]["org_id"] == "test_org"

    def test_generated_at_is_iso_format(self, configured_store):
        """generated_at should be a valid ISO datetime string."""
        data = _get_dashboard_data()
        from datetime import datetime
        # Should not raise
        datetime.fromisoformat(data["generated_at"])


class TestCmdDashboard:

    def test_dashboard_runs_without_crash(self, configured_store, capsys):
        """Terminal dashboard should execute without exceptions."""
        cmd_dashboard()
        captured = capsys.readouterr()
        assert "Judgment" in captured.out or "Sentigent" in captured.out

    def test_dashboard_shows_score(self, configured_store, capsys):
        """Terminal dashboard should display the judgment score."""
        cmd_dashboard()
        captured = capsys.readouterr()
        # Score is 6/7 ≈ 85.7%, should appear somewhere
        assert "85" in captured.out or "86" in captured.out

    def test_dashboard_shows_agent_info(self, configured_store, capsys):
        """Terminal dashboard should show agent configuration."""
        cmd_dashboard()
        captured = capsys.readouterr()
        assert "test_agent" in captured.out
        assert "test_org" in captured.out


class TestDashboardEmpty:

    def test_dashboard_empty_db(self, db_path: str, capsys):
        """Dashboard should handle empty database gracefully."""
        config = SentigentConfig(
            agent_id="empty_agent",
            org_id="test_org",
            db_path=db_path,
        )
        set_config(config)
        try:
            # Create empty store
            MemoryStore(agent_id="empty_agent", org_id="test_org", db_path=db_path)
            cmd_dashboard()
            captured = capsys.readouterr()
            assert "Sentigent" in captured.out
            # Should show 0 or "No outcomes"
            assert "0" in captured.out or "no" in captured.out.lower() or "No" in captured.out
        finally:
            set_config(None)  # type: ignore[arg-type]


class TestWebDashboard:

    def test_web_handler_serves_index(self, configured_store):
        """Web handler should serve HTML at /."""
        from http.server import HTTPServer
        import socket

        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server = HTTPServer(("127.0.0.1", port), DashboardHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.daemon = True
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            body = resp.read().decode()
            assert "Sentigent Dashboard" in body
            assert "<!DOCTYPE html>" in body
            conn.close()
        finally:
            server.server_close()

    def test_web_handler_serves_api_data(self, configured_store):
        """Web handler should serve JSON data at /api/data."""
        from http.server import HTTPServer
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server = HTTPServer(("127.0.0.1", port), DashboardHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.daemon = True
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/data")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert "summary" in data
            assert "config" in data
            assert data["summary"]["total_episodes"] == 8
            conn.close()
        finally:
            server.server_close()

    def test_web_handler_404(self, configured_store):
        """Web handler should return 404 for unknown paths."""
        from http.server import HTTPServer
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server = HTTPServer(("127.0.0.1", port), DashboardHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.daemon = True
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/nonexistent")
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()
        finally:
            server.server_close()
