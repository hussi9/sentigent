#!/usr/bin/env python3
"""Close the learning loop: turn already-answered escalations into precedents.

When you answer a blocker, that answer should become a precedent so the clone resolves the same
class of blocker itself next time. If those write-backs never fired (old/stale server), your
brain has answers but no precedents — the clone stays ungrounded. This backfills them.

    python scripts/backfill_precedents.py            # backfill (idempotent — safe to re-run)
    python scripts/backfill_precedents.py --dry-run  # show what would be created, write nothing
"""
from __future__ import annotations

import json
import os
import sys

from sentigent.memory.store import MemoryStore
from sentigent.operator.backfill import backfill_precedents


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH", os.path.expanduser(f"~/.sentigent/memory_{agent}.db")
    )
    store = MemoryStore(agent_id=agent, org_id=org, db_path=db_path)

    res = backfill_precedents(store, dry_run="--dry-run" in argv)
    verb = "would create" if res["dry_run"] else "created"
    print(json.dumps(res, indent=2))
    print(f"\n{verb} {res['created']} precedent(s) from {res['answered']} answered escalation(s) "
          f"({res['skipped_already_learned']} already learned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
