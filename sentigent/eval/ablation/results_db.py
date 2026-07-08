"""Sprint-scoped sqlite for WS-B ablation arm results.

Persists one row per (task_id, arm) run with {resolved, attempts, repaired}
into a SEPARATE sprint DB (default ``DEFAULT_ABLATION_DB_PATH``) and NEVER into
the operator brain (memory_hussain.db). Mirrors the isolation guard in
``sprint_grader.py``.

See docs/TRUTH-SPRINT-2WEEK.md — WS-B CORE.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass

# Sprint-scoped ablation results DB — kept strictly separate from the operator
# brain (memory_hussain.db). Default lives under the user's home dir.
DEFAULT_ABLATION_DB_PATH = os.path.join(
    os.path.expanduser("~"), ".sentigent", "ablation_results.db"
)


@dataclass
class ResultRow:
    """One persisted ablation arm result."""

    task_id: str
    arm: str
    resolved: bool
    attempts: int
    repaired: bool
    wallclock_s: float = 0.0


class AblationResultsDB:
    """Forward-only recorder of ablation arm results into a sprint DB.

    Writes one row per arm run into a SEPARATE sprint DB (default
    ``DEFAULT_ABLATION_DB_PATH``) and NEVER into memory_hussain.db.
    """

    def __init__(self, db_path: str | None = None) -> None:
        resolved = db_path or DEFAULT_ABLATION_DB_PATH
        # Hard isolation: never open or create the operator brain. Reject any
        # db_path whose basename is memory_hussain.db before touching the FS.
        if os.path.basename(resolved) == "memory_hussain.db":
            raise ValueError(
                "AblationResultsDB refuses to use memory_hussain.db; "
                "sprint runs must record into a separate sprint results DB."
            )
        self.db_path = resolved
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        """Create the sprint DB + results table (forward-only)."""
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    arm TEXT NOT NULL,
                    resolved INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    repaired INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    wallclock_s REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            # Idempotent migration: pre-existing sprint DBs created before the
            # wallclock_s column was added get it ALTERed in cleanly.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
            if "wallclock_s" not in cols:
                conn.execute(
                    "ALTER TABLE results "
                    "ADD COLUMN wallclock_s REAL NOT NULL DEFAULT 0.0"
                )

    def append_result(
        self,
        task_id: str,
        arm: str,
        resolved: bool,
        attempts: int,
        repaired: bool,
        wallclock_s: float = 0.0,
    ) -> None:
        """Append one ablation arm result row."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO results
                    (task_id, arm, resolved, attempts, repaired, timestamp,
                     wallclock_s)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    arm,
                    1 if resolved else 0,
                    attempts,
                    1 if repaired else 0,
                    time.time(),
                    wallclock_s,
                ),
            )

    def existing_pairs(self) -> set[tuple[str, str]]:
        """Return the set of all persisted (task_id, arm) pairs.

        Used by the paired runner to skip already-recorded work so a sprint
        run is resumable.
        """
        with self._connect() as conn:
            cur = conn.execute("SELECT DISTINCT task_id, arm FROM results")
            return {(task_id, arm) for task_id, arm in cur.fetchall()}

    def fetch_all(self) -> list[ResultRow]:
        """Read every persisted result row, oldest first."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT task_id, arm, resolved, attempts, repaired, wallclock_s
                FROM results ORDER BY id ASC
                """
            )
            return [
                ResultRow(
                    task_id=task_id,
                    arm=arm,
                    resolved=bool(resolved),
                    attempts=attempts,
                    repaired=bool(repaired),
                    wallclock_s=wallclock_s,
                )
                for task_id, arm, resolved, attempts, repaired, wallclock_s
                in cur.fetchall()
            ]
