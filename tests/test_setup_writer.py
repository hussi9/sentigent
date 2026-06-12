"""Tests for SetupWriter and MemoryStore setup methods."""
from __future__ import annotations
import sqlite3
import pytest


def _store(tmp_path):
    from sentigent.memory.store import MemoryStore
    return MemoryStore(
        agent_id="test", org_id="org", db_path=str(tmp_path / "t.db")
    )


class TestSetupObservationLog:
    def test_log_and_retrieve_observation(self, tmp_path):
        store = _store(tmp_path)
        store.log_setup_observation(
            tool_name="Bash",
            tool_input="gh pr create --title 'Fix auth'",
            routing_confidence=0.45,
            outcome_signal="success",
        )
        obs = store.get_setup_observations(limit=10)
        assert len(obs) == 1
        assert obs[0]["tool_name"] == "Bash"
        assert abs(obs[0]["routing_confidence"] - 0.45) < 0.001

    def test_get_observations_respects_limit(self, tmp_path):
        store = _store(tmp_path)
        for i in range(10):
            store.log_setup_observation("Bash", f"cmd{i}", 0.5, "success")
        assert len(store.get_setup_observations(limit=3)) == 3


class TestSetupConfig:
    def test_set_and_get_config(self, tmp_path):
        store = _store(tmp_path)
        store.set_setup_config("routing_threshold", "0.65")
        assert store.get_setup_config("routing_threshold") == "0.65"

    def test_get_missing_config_returns_default(self, tmp_path):
        store = _store(tmp_path)
        assert store.get_setup_config("nonexistent", default="0.60") == "0.60"

    def test_set_config_overwrites_existing(self, tmp_path):
        store = _store(tmp_path)
        store.set_setup_config("routing_threshold", "0.60")
        store.set_setup_config("routing_threshold", "0.70")
        assert store.get_setup_config("routing_threshold") == "0.70"


class TestSetupChanges:
    def test_apply_and_list_change(self, tmp_path):
        store = _store(tmp_path)
        change_id = store.apply_setup_change(
            change_type="threshold",
            description="Lower routing threshold from 0.60 to 0.55",
            old_value={"routing_threshold": "0.60"},
            new_value={"routing_threshold": "0.55"},
            revert_payload={"action": "set_config", "key": "routing_threshold", "value": "0.60"},
        )
        assert isinstance(change_id, int)
        changes = store.get_setup_changes()
        assert len(changes) == 1
        assert changes[0]["change_type"] == "threshold"
        assert changes[0]["reverted_at"] is None

    def test_revert_change_marks_reverted_at(self, tmp_path):
        store = _store(tmp_path)
        change_id = store.apply_setup_change(
            change_type="threshold",
            description="test",
            old_value={},
            new_value={"routing_threshold": "0.50"},
            revert_payload={"action": "set_config", "key": "routing_threshold", "value": "0.60"},
        )
        ok = store.revert_setup_change(change_id)
        assert ok is True
        changes = store.get_setup_changes()
        assert changes[0]["reverted_at"] is not None


class TestSetupWriter:
    def test_apply_routing_seed_refresh_writes_change(self, tmp_path):
        from sentigent.setup.writer import SetupWriter
        from sentigent.setup.drift_detector import DriftEvent
        store = _store(tmp_path)
        writer = SetupWriter(store)
        event = DriftEvent(drift_type="routing_confidence", severity="medium",
            description="Low confidence", recommendation="Refresh seeds",
            suggested_change={"action": "refresh_routing_seeds", "current_avg_confidence": 0.42})
        change_id = writer.apply(event)
        assert change_id > 0
        changes = store.get_setup_changes()
        assert len(changes) == 1
        assert changes[0]["change_type"] == "routing_confidence"

    def test_apply_mcp_gap_writes_recommendation(self, tmp_path):
        from sentigent.setup.writer import SetupWriter
        from sentigent.setup.drift_detector import DriftEvent
        store = _store(tmp_path)
        writer = SetupWriter(store)
        event = DriftEvent(drift_type="mcp_gap", severity="medium",
            description="GitHub CLI detected", recommendation="GitHub MCP: use GitHub MCP server",
            suggested_change={"action": "recommend_mcp", "mcp_name": "GitHub MCP", "matched_count": 5})
        change_id = writer.apply(event)
        assert change_id > 0
        changes = store.get_setup_changes()
        assert changes[0]["change_type"] == "mcp_gap"

    def test_revert_applies_revert_action(self, tmp_path):
        from sentigent.setup.writer import SetupWriter
        from sentigent.setup.drift_detector import DriftEvent
        store = _store(tmp_path)
        store.set_setup_config("routing_threshold", "0.55")
        writer = SetupWriter(store)
        event = DriftEvent(drift_type="routing_confidence", severity="low",
            description="Threshold drift", recommendation="Adjust threshold",
            suggested_change={"action": "refresh_routing_seeds", "current_avg_confidence": 0.50})
        change_id = writer.apply(event)
        ok = writer.revert(change_id)
        assert ok is True
        changes = store.get_setup_changes()
        assert changes[0]["reverted_at"] is not None
        assert store.get_setup_config("routing_threshold") == "0.55"


class TestRevertRateTracker:
    def test_zero_changes_returns_stage_1(self, tmp_path):
        from sentigent.setup.revert_tracker import RevertRateTracker
        store = _store(tmp_path)
        tracker = RevertRateTracker(store)
        status = tracker.get_status()
        assert status["stage"] == 1
        assert status["revert_rate"] == 0.0

    def test_all_reverted_is_100_percent(self, tmp_path):
        from sentigent.setup.revert_tracker import RevertRateTracker
        store = _store(tmp_path)
        cid = store.apply_setup_change("threshold", "d", {}, {"v": 1}, {"action": "noop"})
        store.revert_setup_change(cid)
        tracker = RevertRateTracker(store)
        status = tracker.get_status()
        assert status["revert_rate"] == 1.0
        assert status["stage"] == 1

    def test_zero_revert_rate_10_changes_recommends_upgrade(self, tmp_path):
        from sentigent.setup.revert_tracker import RevertRateTracker
        store = _store(tmp_path)
        for i in range(10):
            store.apply_setup_change("threshold", f"change {i}", {}, {"v": i}, {})
        tracker = RevertRateTracker(store)
        status = tracker.get_status()
        assert status["revert_rate"] == 0.0
        assert status["upgrade_available"] is True
