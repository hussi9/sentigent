#!/usr/bin/env python3
"""One-time backfill: mark all pending episodes as 'neutral'.

These 1,000+ episodes happened without crashes or complaints,
so we know they weren't catastrophic. Marking them 'neutral'
unlocks update_baselines_from_episodes() which needs outcome IS NOT NULL.

Run once:
    .venv/bin/python3 claude-plugin/backfill_outcomes.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".sentigent" / "memory_claude_code.db"


def backfill(db_path: Path, dry_run: bool = False) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pending = conn.execute(
        "SELECT trace_id FROM episodes WHERE outcome IS NULL"
    ).fetchall()

    count = len(pending)
    if count == 0:
        print("Nothing to backfill — all episodes already have outcomes.")
        conn.close()
        return 0

    print(f"Found {count} episodes without outcomes.")
    if dry_run:
        print("(dry run — not writing)")
        conn.close()
        return count

    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE episodes
        SET outcome = 'neutral',
            outcome_timestamp = ?,
            outcome_feedback = 'Backfilled: session completed without errors'
        WHERE outcome IS NULL
        """,
        (ts,),
    )
    conn.commit()

    # Now compute baselines from all that data
    print(f"Marked {count} episodes as 'neutral'. Computing baselines...")
    conn.close()

    # Re-open via MemoryStore to use its baseline logic
    from sentigent.core.engine import Sentigent
    judge = Sentigent(profile="code_review", agent_id="claude_code")
    judge._memory.update_baselines_from_episodes()

    baselines = judge._memory.get_baselines()
    print(f"Computed {len(baselines)} baselines:")
    for name, b in baselines.items():
        print(f"  {name}: median={b.median:.2f}  std={b.std:.2f}  n={b.sample_size}")

    print("\nDone. Sentigent will now compute real signals on next tool call.")
    return count


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}. Run Claude Code first.")
        sys.exit(1)
    backfill(DB_PATH, dry_run=dry)
