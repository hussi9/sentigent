#!/usr/bin/env python3
"""Write AGENTS.md from the live clone brain — a learned steering file.

Frontier teams hand-write steering files (conventions, standards, testing
patterns, rules) and they go stale. This generates yours from how you actually
work, so any agent harness that reads AGENTS.md acts the way you would.

    python scripts/export_steering.py            # writes ./AGENTS.md
    python scripts/export_steering.py --print    # print to stdout, don't write
    python scripts/export_steering.py --out docs/AGENTS.md
"""
from __future__ import annotations

import json
import os
import sys

from sentigent.memory.store import MemoryStore
from sentigent.operator.steering_doc import build_steering_doc


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH", os.path.expanduser(f"~/.sentigent/memory_{agent}.db")
    )
    store = MemoryStore(agent_id=agent, org_id=org, db_path=db_path)

    profile: dict = {}
    try:
        latest = store.get_latest_operator_profile()
        if latest:
            profile = json.loads(latest.get("profile_json", "{}")) or {}
    except Exception:
        profile = {}

    project = os.environ.get("SENTIGENT_PROJECT") or os.path.basename(os.getcwd())
    doc = build_steering_doc(store, profile, project=project)

    if "--print" in argv:
        print(doc)
        return 0

    out_path = "AGENTS.md"
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 < len(argv):
            out_path = argv[i + 1]
    out_path = os.path.join(os.getcwd(), out_path) if not os.path.isabs(out_path) else out_path
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(doc)
    print(f"wrote {out_path} ({len(doc)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
