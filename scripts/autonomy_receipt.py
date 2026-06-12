#!/usr/bin/env python3
"""Print the autonomy receipt for a run (default: the latest).

Usage:
    python scripts/autonomy_receipt.py            # latest run
    python scripts/autonomy_receipt.py 7          # a specific run id
    python scripts/autonomy_receipt.py 5 6 7      # several runs (aggregated footer)
"""
from __future__ import annotations

import os
import sqlite3
import sys

from sentigent.memory.store import MemoryStore
from sentigent.operator.receipt import build_receipt, render_markdown


def _latest_run_id(db_path: str) -> int | None:
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(id) FROM operator_runs").fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH",
        os.path.expanduser(f"~/.sentigent/memory_{agent}.db"),
    )
    store = MemoryStore(agent_id=agent, org_id=org, db_path=db_path)

    if argv:
        run_ids = [int(a) for a in argv]
    else:
        latest = _latest_run_id(db_path)
        if latest is None:
            print("No operator runs yet — fly one with operator_start first.")
            return 1
        run_ids = [latest]

    print(render_markdown(build_receipt(store, run_ids)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
