"""Tests for SetupSyncManager — L2 Supabase setup pattern sharing."""
from __future__ import annotations
import sqlite3
import pytest


def _store(tmp_path):
    from sentigent.memory.store import MemoryStore
    return MemoryStore(
        agent_id="test", org_id="org", db_path=str(tmp_path / "t.db")
    )


class TestSetupSyncManager:
    def test_get_validated_changes_excludes_reverted(self, tmp_path):
        from sentigent.setup.sync import SetupSyncManager
        store = _store(tmp_path)
        cid_good = store.apply_setup_change("threshold", "good", {}, {"v": 1}, {})
        cid_bad = store.apply_setup_change("threshold", "reverted", {}, {"v": 2}, {})
        store.revert_setup_change(cid_bad)

        mgr = SetupSyncManager(store)
        validated = mgr.get_validated_changes(min_age_hours=0)
        assert len(validated) == 1
        assert validated[0]["id"] == cid_good

    def test_get_validated_changes_excludes_too_recent(self, tmp_path):
        from sentigent.setup.sync import SetupSyncManager
        store = _store(tmp_path)
        store.apply_setup_change("threshold", "brand new", {}, {"v": 1}, {})
        mgr = SetupSyncManager(store)
        # With min_age_hours=48, nothing qualifies (just applied)
        validated = mgr.get_validated_changes(min_age_hours=48)
        assert validated == []

    def test_format_for_push_excludes_sensitive_fields(self, tmp_path):
        from sentigent.setup.sync import SetupSyncManager
        store = _store(tmp_path)
        store.apply_setup_change(
            "threshold", "desc", {"secret": "hidden"}, {"routing_threshold": "0.55"}, {}
        )
        mgr = SetupSyncManager(store)
        changes = mgr.get_validated_changes(min_age_hours=0)
        formatted = mgr.format_for_push(changes)
        assert len(formatted) == 1
        # Must NOT include old_value (may contain sensitive config values)
        assert "old_value" not in formatted[0]
        assert formatted[0]["change_type"] == "threshold"
        assert "org_id" not in formatted[0]  # anonymized

    def test_get_validated_changes_includes_old_enough(self, tmp_path):
        """A change with applied_at backdated 2h ago passes a min_age_hours=1 filter."""
        from sentigent.setup.sync import SetupSyncManager
        from datetime import datetime, timedelta, timezone

        store = _store(tmp_path)
        cid = store.apply_setup_change("threshold", "old", {}, {"v": 1}, {})

        # Backdate applied_at to 2 hours ago directly in SQLite
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        conn = sqlite3.connect(str(tmp_path / "t.db"))
        conn.execute("UPDATE setup_changes SET applied_at=? WHERE id=?", (two_hours_ago, cid))
        conn.commit()
        conn.close()

        mgr = SetupSyncManager(store)
        validated = mgr.get_validated_changes(min_age_hours=1)
        assert len(validated) == 1
        assert validated[0]["id"] == cid


class TestSyncManagerSetupMethods:
    def test_push_setup_patterns_empty_list_returns_zero_counts(self, tmp_path):
        from sentigent.sync.manager import SyncManager
        mgr = SyncManager(
            org_id="org", agent_id="test",
            db_path=str(tmp_path / "sync.db"),
        )
        result = mgr.push_setup_patterns([])
        assert result == {"pushed": 0, "failed": 0}

    def test_pull_setup_patterns_returns_empty_on_no_supabase(self, tmp_path):
        from sentigent.sync.manager import SyncManager
        mgr = SyncManager(
            org_id="org", agent_id="test",
            db_path=str(tmp_path / "sync.db"),
        )
        # No Supabase configured → _get_client() raises → returns []
        result = mgr.pull_setup_patterns()
        assert result == []
