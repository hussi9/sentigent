"""Tests for InsightsEngine computed metrics."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore


def _make_store(tmp_path: Path) -> MemoryStore:
    db = str(tmp_path / "test.db")
    return MemoryStore(agent_id="test-agent", org_id="test-org", db_path=db)


def _insert_episode(
    store: MemoryStore,
    trace_id: str,
    tool_name: str,
    decision: str,
    outcome: str | None,
    confidence: float,
    timestamp: str = "2026-02-15T10:00:00",
) -> None:
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO episodes
          (trace_id, agent_id, org_id, timestamp, task, context, signals,
           decision, confidence_at_decision, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            store.agent_id,
            store._org_id,
            timestamp,
            f"{tool_name}: test",
            json.dumps({"tool_name": tool_name}),
            "{}",
            decision,
            confidence,
            outcome,
        ),
    )
    conn.commit()
    conn.close()


class TestComputedInsightsTable:
    def test_table_exists_after_init(self, tmp_path):
        store = _make_store(tmp_path)
        conn = sqlite3.connect(store.db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "computed_insights" in tables

    def test_store_and_get_insights(self, tmp_path):
        store = _make_store(tmp_path)
        store.store_computed_insight(
            category="correlation",
            subject="Bash",
            finding="89% correct when confidence > 0.7",
            confidence=0.91,
            recommendation="Trust high-scoring Bash",
            signal_weight=0.15,
        )
        insights = store.get_computed_insights()
        assert len(insights) == 1
        assert insights[0]["subject"] == "Bash"
        assert insights[0]["confidence"] == pytest.approx(0.91)

    def test_get_episodes_for_insights_returns_outcomes(self, tmp_path):
        store = _make_store(tmp_path)
        _insert_episode(store, "t1", "Bash", "proceed", "correct", 0.8)
        _insert_episode(store, "t2", "Bash", "proceed", "incorrect", 0.4)
        _insert_episode(store, "t3", "Write", "proceed", "correct", 0.75)
        episodes = store.get_episodes_for_insights(limit=100)
        assert len(episodes) == 3
        assert all(ep["outcome"] is not None for ep in episodes)


from sentigent.core.insights import InsightsEngine, Insight, SessionReview


class TestInsightsEngine:
    def _engine(self, tmp_path: Path) -> tuple[MemoryStore, InsightsEngine]:
        store = _make_store(tmp_path)
        engine = InsightsEngine(store)
        return store, engine

    def test_brier_score_perfect_calibration(self, tmp_path):
        store, engine = self._engine(tmp_path)
        for i in range(10):
            _insert_episode(store, f"high-{i}", "Bash", "proceed", "correct", 0.9)
        for i in range(10):
            _insert_episode(store, f"low-{i}", "Bash", "proceed", "incorrect", 0.1)
        score = engine._brier_score(store.get_episodes_for_insights())
        assert score < 0.15

    def test_brier_score_terrible_calibration(self, tmp_path):
        store, engine = self._engine(tmp_path)
        for i in range(20):
            _insert_episode(store, f"t-{i}", "Bash", "proceed", "incorrect", 0.95)
        score = engine._brier_score(store.get_episodes_for_insights())
        assert score > 0.5

    def test_compute_correlations_finds_tool_pattern(self, tmp_path):
        store, engine = self._engine(tmp_path)
        for i in range(15):
            _insert_episode(store, f"b-{i}", "Bash", "proceed", "correct", 0.8)
        for i in range(5):
            _insert_episode(store, f"w-{i}", "Write", "proceed", "incorrect", 0.4)
        insights = engine.compute_correlations()
        subjects = [i.subject for i in insights]
        assert any("Bash" in s for s in subjects)

    def test_detect_trends_declining(self, tmp_path):
        from datetime import datetime, timezone
        store, engine = self._engine(tmp_path)
        for i in range(10):
            _insert_episode(store, f"old-{i}", "Bash", "proceed", "correct", 0.85,
                            timestamp="2026-02-01T10:00:00")
        for i in range(10):
            _insert_episode(store, f"new-{i}", "Bash", "proceed", "incorrect", 0.6,
                            timestamp="2026-02-17T10:00:00")
        fake_now = datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc)
        trends = engine.detect_trends(window_days=7, _now=fake_now)
        assert any(t.category == "trend" for t in trends)

    def test_detect_anomaly_escalation_spike(self, tmp_path):
        store, engine = self._engine(tmp_path)
        for i in range(20):
            _insert_episode(store, f"norm-{i}", "Bash", "proceed", "correct", 0.8,
                            timestamp="2026-02-01T10:00:00")
        for i in range(8):
            _insert_episode(store, f"esc-{i}", "Bash", "escalate", "incorrect", 0.2,
                            timestamp="2026-02-17T10:00:00")
        anomalies = engine.detect_anomalies()
        assert len(anomalies) > 0
        assert any("escalat" in a.finding.lower() for a in anomalies)

    def test_compute_session_review(self, tmp_path):
        store, engine = self._engine(tmp_path)
        _insert_episode(store, "good-1", "Bash", "escalate", "incorrect", 0.2)
        _insert_episode(store, "bad-1", "Bash", "proceed", "incorrect", 0.8)
        review = engine.compute_session_review(last_n=10)
        assert isinstance(review, SessionReview)
        assert len(review.good_decisions) >= 1
        assert len(review.concerns) >= 1

    def test_refresh_stores_insights_in_db(self, tmp_path):
        store, engine = self._engine(tmp_path)
        for i in range(15):
            _insert_episode(store, f"e-{i}", "Bash", "proceed", "correct", 0.85)
        engine.refresh_if_stale()
        stored = store.get_computed_insights()
        assert len(stored) > 0


class TestInsightsWiring:
    def test_sentigent_has_insights_attribute(self, tmp_path):
        """Sentigent engine should have _insights attribute after init."""
        from sentigent.core.engine import Sentigent
        engine = Sentigent(
            profile="code_review",
            agent_id="test-wire",
            db_path=str(tmp_path / "wire.db"),
        )
        assert hasattr(engine, "_insights")
        from sentigent.core.insights import InsightsEngine
        assert isinstance(engine._insights, InsightsEngine)

    def test_refresh_called_every_10_outcomes(self, tmp_path):
        """InsightsEngine.refresh_if_stale should be called when outcome count hits multiple of 10."""
        from unittest.mock import MagicMock, patch
        from sentigent.core.engine import Sentigent

        engine = Sentigent(
            profile="code_review",
            agent_id="test-refresh",
            db_path=str(tmp_path / "refresh.db"),
        )
        mock_refresh = MagicMock()
        engine._insights.refresh_if_stale = mock_refresh

        # Seed 10 episodes directly into memory so record_outcome can find them
        import sqlite3, json
        conn = sqlite3.connect(engine._memory.db_path)
        for i in range(10):
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (trace_id, agent_id, org_id, timestamp, task, context, signals,
                    decision, confidence_at_decision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"seed-{i}", engine._agent_id, engine._memory._org_id,
                 "2026-02-18T10:00:00", "echo test", "{}", "{}", "proceed", 0.8),
            )
        conn.commit()
        conn.close()

        for i in range(10):
            engine.record_outcome(f"seed-{i}", "correct")

        assert mock_refresh.call_count >= 1


class TestMcpInsightsTools:
    def test_sentigent_insights_returns_valid_json(self, tmp_path):
        import json
        from unittest.mock import patch, MagicMock
        from sentigent.core.insights import Insight
        import sentigent.mcp_server as mcp_module

        mock_judge = MagicMock()
        mock_judge._insights.compute_correlations.return_value = [
            Insight("correlation", "Bash", "89% correct", 0.91, "Trust Bash", 0.2)
        ]
        mock_judge._insights.detect_trends.return_value = []
        mock_judge._insights.detect_anomalies.return_value = []
        mock_judge._insights._brier_score.return_value = 0.12
        mock_judge._memory.get_episodes_for_insights.return_value = []

        with patch.object(mcp_module, "_get_judge", return_value=mock_judge):
            result = mcp_module.sentigent_insights()

        data = json.loads(result)
        assert "correlations" in data
        assert "trends" in data
        assert "anomalies" in data
        assert "brier_score" in data
        assert "recommendations" in data

    def test_sentigent_review_returns_session_structure(self, tmp_path):
        import json
        from unittest.mock import patch, MagicMock
        from sentigent.core.insights import SessionReview
        import sentigent.mcp_server as mcp_module

        mock_judge = MagicMock()
        mock_review = SessionReview(
            good_decisions=[{"task": "echo", "tool": "Bash",
                             "decision": "proceed", "outcome": "correct",
                             "confidence": 0.9}],
            concerns=[],
            session_score=0.85,
            top_insight="Trust Bash when score > 0.7",
            brier_score=0.12,
            total_reviewed=1,
        )
        mock_judge._insights.compute_session_review.return_value = mock_review

        with patch.object(mcp_module, "_get_judge", return_value=mock_judge):
            result = mcp_module.sentigent_review()

        data = json.loads(result)
        assert "good_decisions" in data
        assert "concerns" in data
        assert "session_score" in data
        assert "brier_score" in data

    def test_sentigent_trends_returns_daily_breakdown(self, tmp_path):
        import json
        from unittest.mock import patch, MagicMock
        from sentigent.core.insights import Insight
        import sentigent.mcp_server as mcp_module

        mock_judge = MagicMock()
        mock_judge._memory.get_episodes_for_insights.return_value = []
        mock_judge._insights.detect_trends.return_value = []

        with patch.object(mcp_module, "_get_judge", return_value=mock_judge):
            result = mcp_module.sentigent_trends()

        data = json.loads(result)
        assert "window_days" in data
        assert "daily_breakdown" in data
        assert "trend_findings" in data


class TestInsightsFeedbackLoop:
    def test_evaluate_metadata_includes_insight_weights(self, tmp_path):
        """evaluate() should attach high-confidence insight weights to decision metadata."""
        from sentigent.core.engine import Sentigent
        from sentigent.core.insights import Insight

        engine = Sentigent(
            profile="code_review",
            agent_id="test-feedback",
            db_path=str(tmp_path / "fb.db"),
        )
        # Inject a high-confidence insight with signal_weight
        mock_insight = Insight(
            category="correlation",
            subject="Bash",
            finding="89% correct",
            confidence=0.92,
            recommendation="Trust Bash",
            signal_weight=0.2,
        )
        engine._insights.get_cached_insights = lambda: [mock_insight]

        decision = engine.evaluate(
            task="Bash: echo test",
            context={"tool_name": "Bash"},
        )
        assert "insight_weights" in decision.metadata
        assert "Bash" in decision.metadata["insight_weights"]
