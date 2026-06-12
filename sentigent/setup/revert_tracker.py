"""RevertRateTracker — tracks the setup agent's own revert rate."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore

_UPGRADE_REVERT_THRESHOLD = 0.05
_UPGRADE_MIN_CHANGES = 10

class RevertRateTracker:
    """Track revert rate and determine autonomy stage."""
    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def get_status(self) -> dict[str, Any]:
        """Return current revert rate, autonomy stage, and upgrade eligibility.
        Returns dict with: stage, revert_rate, applied, reverted, upgrade_available.
        """
        changes = self._store.get_setup_changes(limit=500, include_reverted=True)
        applied = len(changes)
        reverted = sum(1 for c in changes if c.get("reverted_at") is not None)
        revert_rate = (reverted / applied) if applied > 0 else 0.0
        upgrade_available = (applied >= _UPGRADE_MIN_CHANGES and revert_rate <= _UPGRADE_REVERT_THRESHOLD)
        current_stage = int(self._store.get_setup_config("autonomy_stage", default="1"))
        return {
            "stage": current_stage,
            "revert_rate": round(revert_rate, 4),
            "applied": applied,
            "reverted": reverted,
            "upgrade_available": upgrade_available,
            "upgrade_threshold": _UPGRADE_REVERT_THRESHOLD,
            "upgrade_min_changes": _UPGRADE_MIN_CHANGES,
        }

    def upgrade_to_stage_2(self) -> bool:
        """Upgrade autonomy to stage 2. Returns True if eligible."""
        status = self.get_status()
        if not status["upgrade_available"]:
            return False
        self._store.set_setup_config("autonomy_stage", "2")
        return True
