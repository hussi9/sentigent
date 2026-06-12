"""SetupWriter — applies drift corrections with full Apply+Undo semantics.

Every change is logged to setup_changes with a revert_payload so it can be
undone via a single sentigent_setup_agent(action='revert', change_id=N) call.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore
    from sentigent.setup.drift_detector import DriftEvent

logger = logging.getLogger(__name__)


class SetupWriter:
    """Apply drift corrections and log full revert payloads."""

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def apply(self, event: "DriftEvent") -> int:
        """Apply a detected drift correction and return the change_id.

        Config mutations (e.g., routing_threshold) only happen after the
        change log row is confirmed written. If logging fails, no config
        is mutated and -1 is returned.

        Args:
            event: DriftEvent from DriftDetector.detect().

        Returns:
            change_id (row ID in setup_changes table), or -1 on error.
        """
        suggested = event.suggested_change
        action = suggested.get("action", "")

        old_value, new_value, revert_payload, config_mutation = self._build_payloads(action, suggested)

        change_id = self._store.apply_setup_change(
            change_type=event.drift_type,
            description=event.description,
            old_value=old_value,
            new_value=new_value,
            revert_payload=revert_payload,
            autonomy_stage=1,
        )

        if change_id > 0 and config_mutation:
            self._store.set_setup_config(config_mutation["key"], config_mutation["value"])

        return change_id

    def revert(self, change_id: int) -> bool:
        """Undo a previously applied change.

        Reads the revert_payload from setup_changes by ID and executes the
        inverse action.

        Args:
            change_id: Row ID from apply_setup_change().

        Returns:
            True if reverted successfully.
        """
        target = self._store.get_setup_change_by_id(change_id)
        if not target:
            return False

        revert = json.loads(target.get("revert_payload") or "{}")
        action = revert.get("action", "")

        if action == "restore_config":
            key = revert.get("key")
            value = revert.get("value")
            if key is not None and value is not None:
                self._store.set_setup_config(key, value)
            else:
                logger.warning(
                    "revert: restore_config payload missing key/value for change_id=%s", change_id
                )

        return self._store.revert_setup_change(change_id)

    def _build_payloads(
        self, action: str, suggested: dict[str, Any]
    ) -> tuple[dict, dict, dict, dict | None]:
        """Return (old_value, new_value, revert_payload, config_mutation).

        config_mutation is a {"key": ..., "value": ...} dict applied only
        after the change log row is confirmed written, or None if no config
        write is needed.
        """
        if action == "refresh_routing_seeds":
            current_threshold = self._store.get_setup_config(
                "routing_threshold", default="0.60"
            )
            new_threshold = str(max(0.45, float(current_threshold) - 0.05))
            return (
                {"routing_threshold": current_threshold},
                {"routing_threshold": new_threshold},
                {"action": "restore_config", "key": "routing_threshold", "value": current_threshold},
                {"key": "routing_threshold", "value": new_threshold},
            )

        if action == "recommend_mcp":
            mcp_name = suggested.get("mcp_name", "unknown")
            return (
                {},
                {"mcp_recommendation": mcp_name, "matched_count": suggested.get("matched_count", 0)},
                {"action": "noop"},
                None,
            )

        return ({}, suggested, {"action": "noop"}, None)
