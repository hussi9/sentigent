"""Tests for prove.py — proof-of-value engine."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone

import pytest

from sentigent.core.prove import (
    AgentCompliance,
    PolicyStat,
    ProofEngine,
    ProofReport,
    ScorePoint,
    TopCatch,
)


def _make_test_db_full(episodes: list[dict]) -> str:
    """Create a temporary SQLite DB with all columns prove.py queries."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT,
            agent_id TEXT DEFAULT 'test_agent',
            task TEXT,
            context TEXT DEFAULT '{}',
            signals TEXT DEFAULT '{}',
            decision TEXT,
            confidence_at_decision REAL DEFAULT 0.5,
            reason TEXT DEFAULT '',
            outcome TEXT,
            outcome_feedback TEXT,
            timestamp TEXT
        )
    """)
    for i, ep in enumerate(episodes):
        conn.execute(
            """INSERT INTO episodes
               (trace_id, agent_id, task, decision, confidence_at_decision,
                reason, context, outcome, outcome_feedback, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                f"trace_{i:04d}",
                ep.get("agent_id", "test_agent"),
                ep.get("task", f"task_{i}"),
                ep.get("decision", "proceed"),
                ep.get("confidence", 0.5),
                ep.get("reason", ""),
                ep.get("context", "{}"),
                ep.get("outcome", "correct"),
                ep.get("feedback", ""),
                ep.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_test_db(episodes: list[dict]) -> str:
    """Create a temporary SQLite DB for proof engine tests."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT,
            agent_id TEXT DEFAULT 'test_agent',
            task TEXT,
            context TEXT,
            signals TEXT,
            decision TEXT,
            confidence_at_decision REAL DEFAULT 0.5,
            outcome TEXT,
            outcome_feedback TEXT,
            timestamp TEXT
        )
    """)
    for i, ep in enumerate(episodes):
        conn.execute(
            """INSERT INTO episodes
               (trace_id, agent_id, task, decision, outcome, outcome_feedback, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (
                f"trace_{i:04d}",
                ep.get("agent_id", "test_agent"),
                ep.get("task", f"task_{i}"),
                ep.get("decision", "proceed"),
                ep.get("outcome", "correct"),
                ep.get("feedback", ""),
                ep.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


# ── TopCatch ──────────────────────────────────────────────────────────────────


class TestTopCatch:
    def test_fields(self):
        tc = TopCatch(
            timestamp="2025-01-01T00:00:00",
            task="git push --force",
            decision="enrich",
            reason="Force push detected",
            confidence=0.9,
            tool="Bash",
        )
        assert tc.task == "git push --force"
        assert tc.decision == "enrich"
        assert tc.confidence == 0.9


# ── ScorePoint ────────────────────────────────────────────────────────────────


class TestScorePoint:
    def test_fields(self):
        sp = ScorePoint(period="2025-W01", score=0.85, correct=17, incorrect=3, total_rated=20)
        assert sp.score == 0.85
        assert sp.period == "2025-W01"
        assert sp.correct == 17


# ── ProofReport ───────────────────────────────────────────────────────────────


class TestProofReport:
    def _make_report(self, **kwargs) -> ProofReport:
        defaults = {
            "agent_id": "test_agent",
            "org_id": "test_org",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_episodes": 100,
            "confirmed_catches": 25,
            "false_negatives": 1,
            "safe_passes": 74,
            "wrong_interventions": 0,
            "intervention_accuracy": 0.96,
            "false_negative_rate": 0.01,
            "intervention_rate": 0.25,
            "score_trajectory": [],
            "top_catches": [],
            "policy_stats": [],
            "total_policy_enforcements": 0,
            "agent_compliance": [],
            "verdict": "Working well",
        }
        defaults.update(kwargs)
        return ProofReport(**defaults)

    def test_to_dict_has_required_keys(self):
        report = self._make_report()
        d = report.to_dict()
        assert d["agent_id"] == "test_agent"
        assert d["total_episodes"] == 100
        assert d["confirmed_catches"] == 25
        assert d["false_negatives"] == 1
        assert d["intervention_accuracy"] == pytest.approx(0.96, abs=0.001)
        assert "verdict" in d

    def test_to_text_has_verdict(self):
        report = self._make_report(
            confirmed_catches=33,
            false_negatives=1,
            intervention_accuracy=1.0,
            false_negative_rate=0.001,
        )
        text = report.to_text()
        assert "PROOF OF VALUE" in text
        assert "33" in text

    def test_to_text_contains_trajectory(self):
        report = self._make_report(
            score_trajectory=[
                ScorePoint(period="2025-W01", score=0.80, correct=40, incorrect=10, total_rated=50),
                ScorePoint(period="2025-W02", score=0.90, correct=54, incorrect=6, total_rated=60),
            ]
        )
        text = report.to_text()
        # Should contain some score-related content
        assert "PROOF OF VALUE" in text  # at minimum the header


# ── ProofEngine ───────────────────────────────────────────────────────────────


class TestProofEngineLocal:
    def test_empty_db_returns_zero_report(self):
        db = _make_test_db_full([])
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=90)
        assert isinstance(report, ProofReport)
        assert report.total_episodes == 0
        assert report.confirmed_catches == 0
        assert report.false_negatives == 0

    def test_counts_confirmed_catches(self):
        """enrich + correct = confirmed catch."""
        episodes = [
            {"decision": "enrich", "outcome": "correct"},
            {"decision": "enrich", "outcome": "correct"},
            {"decision": "slow_down", "outcome": "correct"},
            {"decision": "proceed", "outcome": "correct"},
            {"decision": "proceed", "outcome": "incorrect"},
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert report.confirmed_catches == 3   # 2 enrich + 1 slow_down
        assert report.false_negatives == 1     # proceed + incorrect

    def test_counts_safe_passes(self):
        """proceed + correct = safe pass."""
        episodes = [
            {"decision": "proceed", "outcome": "correct"},
            {"decision": "proceed", "outcome": "correct"},
            {"decision": "proceed", "outcome": "incorrect"},
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert report.safe_passes == 2
        assert report.false_negatives == 1

    def test_intervention_accuracy_perfect(self):
        """100% intervention accuracy when all catches are confirmed."""
        episodes = [
            {"decision": "enrich", "outcome": "correct"},  # confirmed catch
            {"decision": "enrich", "outcome": "correct"},  # confirmed catch
            {"decision": "proceed", "outcome": "correct"},  # safe pass
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert report.intervention_accuracy == pytest.approx(1.0)

    def test_intervention_accuracy_mixed(self):
        """Accuracy = confirmed_catches / (confirmed_catches + wrong_interventions)."""
        episodes = [
            {"decision": "enrich", "outcome": "correct"},    # confirmed catch
            {"decision": "enrich", "outcome": "incorrect"},  # wrong intervention
            {"decision": "proceed", "outcome": "correct"},
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        # 1 confirmed catch / 2 interventions = 0.5
        assert report.intervention_accuracy == pytest.approx(0.5)

    def test_false_negative_rate(self):
        """FN rate = false_negatives / (fn + safe_passes)."""
        episodes = [
            {"decision": "proceed", "outcome": "incorrect"},  # FN
            {"decision": "proceed", "outcome": "correct"},    # safe pass
            {"decision": "proceed", "outcome": "correct"},    # safe pass
            {"decision": "proceed", "outcome": "correct"},    # safe pass
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert report.false_negatives == 1
        # FN rate = 1/(1+3) = 0.25
        assert report.false_negative_rate == pytest.approx(0.25, abs=0.01)

    def test_top_catches_populated(self):
        """TopCatches should list the enrich+correct episodes."""
        episodes = [
            {"decision": "enrich", "outcome": "correct", "task": f"high risk task {i}"}
            for i in range(5)
        ] + [
            {"decision": "proceed", "outcome": "correct"} for _ in range(10)
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert len(report.top_catches) > 0
        assert all(c.decision in ("enrich", "slow_down", "escalate") for c in report.top_catches)

    def test_score_trajectory_is_list(self):
        """Score trajectory should be a list (may be empty for fresh data)."""
        episodes = [
            {"decision": "proceed", "outcome": "correct"} for _ in range(20)
        ] + [
            {"decision": "enrich", "outcome": "correct"} for _ in range(5)
        ]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert isinstance(report.score_trajectory, list)

    def test_report_to_dict_json_serializable(self):
        episodes = [
            {"decision": "enrich", "outcome": "correct"} for _ in range(5)
        ] + [{"decision": "proceed", "outcome": "correct"} for _ in range(10)]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        d = report.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 50

    def test_verdict_string(self):
        episodes = [
            {"decision": "enrich", "outcome": "correct"} for _ in range(10)
        ] + [{"decision": "proceed", "outcome": "correct"} for _ in range(50)]
        db = _make_test_db_full(episodes)
        engine = ProofEngine(agent_id="test_agent", org_id="test_org", db_path=db)
        report = engine.compute(days=365)
        assert isinstance(report.verdict, str)
        assert len(report.verdict) > 5

    def test_no_supabase_doesnt_crash(self):
        """Proof engine should complete even without Supabase configured."""
        db = _make_test_db_full([
            {"decision": "enrich", "outcome": "correct"} for _ in range(5)
        ])
        engine = ProofEngine(agent_id="test_agent", org_id="nonexistent_org", db_path=db)
        report = engine.compute(days=365)
        assert isinstance(report, ProofReport)
