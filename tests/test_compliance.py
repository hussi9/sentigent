"""Tests for compliance metrics and audit export.

Tests cover:
- Compliance metrics computation
- Policy adherence calculation
- High-risk action tracking
- Export CLI (CSV and JSON formats)
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sentigent.config import SentigentConfig, set_config
from sentigent.dashboard import _query_compliance_metrics


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Create a temporary SQLite database with episodes table."""
    db_path = str(tmp_path / "test_compliance.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            trace_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            org_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            task TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '{}',
            agent_state TEXT NOT NULL DEFAULT '{}',
            signals TEXT NOT NULL DEFAULT '{}',
            decision TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            confidence_at_decision REAL DEFAULT 0.5,
            outcome TEXT,
            outcome_timestamp TEXT,
            outcome_feedback TEXT
        );
        CREATE TABLE IF NOT EXISTS procedural_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT,
            org_id TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            condition TEXT NOT NULL DEFAULT '{}',
            learned_action TEXT NOT NULL,
            success_rate REAL DEFAULT 0.0,
            sample_size INTEGER DEFAULT 0,
            last_reinforced TEXT,
            created_from TEXT DEFAULT 'layer_1'
        );
        CREATE TABLE IF NOT EXISTS semantic_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id TEXT NOT NULL,
            agent_id TEXT,
            metric_name TEXT NOT NULL,
            baseline_data TEXT NOT NULL DEFAULT '{}',
            source TEXT DEFAULT 'operational',
            last_updated TEXT NOT NULL,
            sample_size INTEGER DEFAULT 0,
            UNIQUE(org_id, agent_id, metric_name)
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_episode(
    db_path: str,
    trace_id: str,
    agent_id: str,
    task: str,
    decision: str,
    outcome: str | None = None,
    confidence: float = 0.5,
    timestamp: str | None = None,
) -> None:
    """Helper to insert a test episode."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO episodes
        (trace_id, agent_id, org_id, timestamp, task, decision,
         confidence_at_decision, outcome)
        VALUES (?, ?, 'test_org', ?, ?, ?, ?, ?)
        """,
        (trace_id, agent_id, ts, task, decision, confidence, outcome),
    )
    conn.commit()
    conn.close()


# ─── Compliance Metrics Tests ──────────────────────────────────────────────

class TestComplianceMetrics:
    """Tests for _query_compliance_metrics."""

    def test_empty_database(self, tmp_db: str) -> None:
        """Empty database returns zero metrics."""
        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        assert metrics["total_actions"] == 0
        assert metrics["compliant_actions"] == 0
        assert metrics["policy_adherence_pct"] == 100.0
        assert metrics["violations_caught"] == 0

    def test_all_proceed_actions(self, tmp_db: str) -> None:
        """All proceed actions = 100% adherence."""
        for i in range(10):
            _insert_episode(tmp_db, f"trace_{i}", "test_agent",
                          f"Bash: echo {i}", "proceed")

        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        assert metrics["total_actions"] == 10
        assert metrics["compliant_actions"] == 10
        assert metrics["policy_adherence_pct"] == 100.0
        assert metrics["violations_caught"] == 0

    def test_some_interventions(self, tmp_db: str) -> None:
        """Mix of proceed and interventions calculates correctly."""
        for i in range(8):
            _insert_episode(tmp_db, f"proceed_{i}", "test_agent",
                          f"Bash: echo {i}", "proceed")
        _insert_episode(tmp_db, "escalate_1", "test_agent",
                       "Bash: git push --force origin main", "escalate")
        _insert_episode(tmp_db, "slow_1", "test_agent",
                       "Edit: large_file.py (200 lines)", "slow_down")

        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        assert metrics["total_actions"] == 10
        assert metrics["violations_caught"] == 2
        assert metrics["compliant_actions"] == 8
        assert metrics["policy_adherence_pct"] == 80.0

    def test_high_risk_tracking(self, tmp_db: str) -> None:
        """High-risk actions are tracked correctly."""
        _insert_episode(tmp_db, "safe_1", "test_agent",
                       "Bash: echo hello", "proceed")
        _insert_episode(tmp_db, "risky_1", "test_agent",
                       "Bash: git push --force origin main", "escalate")
        _insert_episode(tmp_db, "risky_2", "test_agent",
                       "Bash: rm -rf /tmp/old", "escalate")
        _insert_episode(tmp_db, "risky_3", "test_agent",
                       "Bash: deploy production", "slow_down")

        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        assert metrics["high_risk_total"] >= 2  # At least the force push and rm -rf
        assert metrics["high_risk_reviewed"] >= 2  # These were escalated/slowed_down

    def test_agent_isolation(self, tmp_db: str) -> None:
        """Metrics are scoped to the specific agent."""
        _insert_episode(tmp_db, "agent1_1", "agent_1",
                       "Bash: echo 1", "proceed")
        _insert_episode(tmp_db, "agent2_1", "agent_2",
                       "Bash: echo 2", "escalate")

        metrics_1 = _query_compliance_metrics(tmp_db, "agent_1")
        assert metrics_1["total_actions"] == 1
        assert metrics_1["violations_caught"] == 0

        metrics_2 = _query_compliance_metrics(tmp_db, "agent_2")
        assert metrics_2["total_actions"] == 1
        assert metrics_2["violations_caught"] == 1

    def test_includes_active_policies(self, tmp_db: str) -> None:
        """Metrics include count of active policies."""
        _insert_episode(tmp_db, "ep_1", "test_agent",
                       "Bash: echo hello", "proceed")
        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        # Default policies should be loaded
        assert metrics["active_policies"] > 0
        assert isinstance(metrics["policy_summary"], list)

    def test_high_risk_review_pct_no_high_risk(self, tmp_db: str) -> None:
        """When no high-risk actions, review percentage is 100%."""
        _insert_episode(tmp_db, "safe_1", "test_agent",
                       "Bash: echo hello", "proceed")
        metrics = _query_compliance_metrics(tmp_db, "test_agent")
        assert metrics["high_risk_total"] == 0
        assert metrics["high_risk_review_pct"] == 100.0


# ─── Export Tests ───────────────────────────────────────────────────────────

class TestExport:
    """Tests for the export CLI command data."""

    def test_export_csv_format(self, tmp_db: str) -> None:
        """Verify CSV export produces valid CSV with expected columns."""
        # Insert test data
        for i in range(5):
            _insert_episode(tmp_db, f"exp_{i}", "test_agent",
                          f"Bash: command_{i}", "proceed", outcome="correct")

        # Query the data directly (same as export does)
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, timestamp, task, decision,
                   confidence_at_decision, outcome, outcome_feedback, signals
            FROM episodes WHERE agent_id = ?
            ORDER BY timestamp ASC
            """,
            ("test_agent",),
        ).fetchall()
        conn.close()

        # Format as CSV (mimicking cli._cmd_export)
        records = [
            {
                "trace_id": row["trace_id"],
                "timestamp": row["timestamp"],
                "task": row["task"],
                "decision": row["decision"],
                "confidence": row["confidence_at_decision"],
                "outcome": row["outcome"] or "",
                "feedback": row["outcome_feedback"] or "",
                "signals": row["signals"],
            }
            for row in rows
        ]

        buf = io.StringIO()
        fieldnames = ["trace_id", "timestamp", "task", "decision",
                      "confidence", "outcome", "feedback", "signals"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
        csv_content = buf.getvalue()

        # Verify CSV is valid
        reader = csv.DictReader(io.StringIO(csv_content))
        csv_records = list(reader)
        assert len(csv_records) == 5
        assert csv_records[0]["trace_id"] == "exp_0"
        assert csv_records[0]["decision"] == "proceed"
        assert csv_records[0]["outcome"] == "correct"

    def test_export_json_format(self, tmp_db: str) -> None:
        """Verify JSON export produces valid JSON with expected structure."""
        for i in range(3):
            _insert_episode(tmp_db, f"json_{i}", "test_agent",
                          f"Bash: cmd_{i}", "proceed", outcome="correct")

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, timestamp, task, decision,
                   confidence_at_decision, outcome, outcome_feedback, signals
            FROM episodes WHERE agent_id = ?
            ORDER BY timestamp ASC
            """,
            ("test_agent",),
        ).fetchall()
        conn.close()

        records = [
            {
                "trace_id": row["trace_id"],
                "timestamp": row["timestamp"],
                "task": row["task"],
                "decision": row["decision"],
                "confidence": row["confidence_at_decision"],
                "outcome": row["outcome"] or "",
                "feedback": row["outcome_feedback"] or "",
                "signals": row["signals"],
            }
            for row in rows
        ]

        json_content = json.dumps(records, indent=2, default=str)
        parsed = json.loads(json_content)
        assert len(parsed) == 3
        assert parsed[0]["trace_id"] == "json_0"
        assert parsed[0]["decision"] == "proceed"

    def test_empty_export(self, tmp_db: str) -> None:
        """Export with no data produces empty list."""
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM episodes WHERE agent_id = ?",
            ("nonexistent_agent",),
        ).fetchall()
        conn.close()
        assert len(rows) == 0
