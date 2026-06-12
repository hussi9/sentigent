#!/usr/bin/env python3
"""Show the flight summary — what your clone did, and what it's become.

    python scripts/flight_summary.py                 # all-time panel
    python scripts/flight_summary.py --since-hours 12 # also show "this flight" for the window
"""
from __future__ import annotations

import os
import sys
import time

from sentigent.memory.store import MemoryStore
from sentigent.operator.flight_summary import cumulative_stats, session_stats, render_panel


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH", os.path.expanduser(f"~/.sentigent/memory_{agent}.db")
    )
    store = MemoryStore(agent_id=agent, org_id=org, db_path=db_path)

    session = None
    if "--since-hours" in argv:
        i = argv.index("--since-hours")
        hours = float(argv[i + 1]) if i + 1 < len(argv) else 24.0
        session = session_stats(store, since_ts=time.time() - hours * 3600)

    print(render_panel(cumulative_stats(store), session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
