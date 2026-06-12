"""SetupSyncManager — push validated setup changes to L2 Supabase.

Validated = not reverted + older than min_age_hours (default 48h).
Patterns are anonymized before push: no old_value, no org_id in payload.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore

_MIN_AGE_HOURS = 48  # a change must survive 48h without revert before sharing


class SetupSyncManager:
    """Push validated local setup changes to L2 for org-wide sharing."""

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def get_validated_changes(
        self, min_age_hours: float = _MIN_AGE_HOURS
    ) -> list[dict[str, Any]]:
        """Return changes that are not reverted and older than min_age_hours."""
        changes = self._store.get_setup_changes(limit=500, include_reverted=False)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)
        validated = []
        for c in changes:
            try:
                applied_at = datetime.fromisoformat(c["applied_at"])
                if applied_at.tzinfo is None:
                    applied_at = applied_at.replace(tzinfo=timezone.utc)
                if applied_at <= cutoff:
                    validated.append(c)
            except Exception:
                continue
        return validated

    def format_for_push(
        self, changes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Anonymize and format changes for Supabase push.

        Removes: old_value (may contain sensitive config values), org_id, agent_id,
        revert_payload, reverted_at.
        """
        result = []
        for c in changes:
            try:
                new_value = json.loads(c.get("new_value") or "{}")
            except Exception:
                logger.debug("format_for_push: failed to parse new_value for change_id=%s", c.get("id"))
                new_value = {}
            result.append({
                "change_type": c.get("change_type", ""),
                "description": c.get("description", ""),
                "new_value": new_value,
                "source_agent_id": self._store.agent_id,
            })
        return result

    def push(self, sync_manager: Any) -> dict[str, Any]:
        """Push validated changes to Supabase via SyncManager.

        Args:
            sync_manager: A SyncManager instance with Supabase connection.

        Returns:
            Dict with pushed/failed counts.
        """
        validated = self.get_validated_changes()
        formatted = self.format_for_push(validated)
        return sync_manager.push_setup_patterns(formatted)
