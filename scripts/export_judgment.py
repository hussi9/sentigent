#!/usr/bin/env python3
"""Write docs/JUDGMENT.md from the live clone brain.

Run this so any agent (or teammate) can read how you decide, straight from the repo.

    python scripts/export_judgment.py            # writes docs/JUDGMENT.md
    python scripts/export_judgment.py --print    # print to stdout, don't write
"""
from __future__ import annotations

import json
import os
import sys

from sentigent.memory.store import MemoryStore
from sentigent.operator.judgment_doc import build_judgment_doc


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH", os.path.expanduser(f"~/.sentigent/memory_{agent}.db")
    )
    store = MemoryStore(agent_id=agent, org_id=org, db_path=db_path)

    profile = {}
    try:
        latest = store.get_latest_operator_profile()
        if latest:
            profile = json.loads(latest.get("profile_json", "{}")) or {}
    except Exception:
        profile = {}

    doc = build_judgment_doc(store, profile)

    if "--print" in argv:
        print(doc)
        return 0

    out_dir = os.path.join(os.getcwd(), "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "JUDGMENT.md")
    with open(out_path, "w") as f:
        f.write(doc)
    print(f"wrote {out_path} ({len(doc)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
