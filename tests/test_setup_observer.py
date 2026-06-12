"""Tests for SetupObserver — rolling window observation logger."""
from __future__ import annotations
from pathlib import Path
import pytest


def _store(tmp_path: Path):
    from sentigent.memory.store import MemoryStore
    return MemoryStore(
        agent_id="test", org_id="org", db_path=str(tmp_path / "t.db")
    )


class TestSetupObserver:
    def test_observe_logs_to_store(self, tmp_path):
        from sentigent.setup.observer import SetupObserver
        store = _store(tmp_path)
        obs = SetupObserver(store)
        obs.observe(
            tool_name="Bash",
            tool_input="gh pr create --title fix",
            routing_confidence=0.45,
            exit_code=0,
        )
        rows = store.get_setup_observations(limit=5)
        assert len(rows) == 1
        assert rows[0]["outcome_signal"] == "success"

    def test_non_zero_exit_code_is_failure(self, tmp_path):
        from sentigent.setup.observer import SetupObserver
        store = _store(tmp_path)
        obs = SetupObserver(store)
        obs.observe("Bash", "broken cmd", 0.3, exit_code=1)
        rows = store.get_setup_observations()
        assert rows[0]["outcome_signal"] == "failure"

    def test_safe_tools_are_not_logged(self, tmp_path):
        from sentigent.setup.observer import SetupObserver
        store = _store(tmp_path)
        obs = SetupObserver(store)
        obs.observe("Read", "/some/file.py", 0.9, exit_code=0)
        assert store.get_setup_observations() == []

    def test_get_window_returns_recent_n(self, tmp_path):
        from sentigent.setup.observer import SetupObserver
        store = _store(tmp_path)
        obs = SetupObserver(store)
        for i in range(10):
            obs.observe("Bash", f"cmd {i}", 0.5, exit_code=0)
        window = obs.get_window(size=5)
        assert len(window) == 5

    def test_observe_with_no_exit_code_defaults_unknown(self, tmp_path):
        from sentigent.setup.observer import SetupObserver
        store = _store(tmp_path)
        obs = SetupObserver(store)
        obs.observe("Edit", "some content", 0.6)
        rows = store.get_setup_observations()
        assert rows[0]["outcome_signal"] == "unknown"
