#!/usr/bin/env python3
"""Sentigent brain doctor — vital signs + silent-failure detection.

    python scripts/doctor.py            # human summary + JSON, exit 1 if warnings

Catches the failure modes a code review found the hard way: answers recorded but no precedents
(stale-server / learn loop not firing), and precedents with no calibration (static thresholds).
"""
from __future__ import annotations

import json
import os
import sys

from sentigent.memory.store import MemoryStore
from sentigent.operator.doctor import health_report


def main(argv: list[str]) -> int:
    agent = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    org = os.environ.get("SENTIGENT_ORG_ID", agent)
    db_path = os.environ.get(
        "SENTIGENT_DB_PATH", os.path.expanduser(f"~/.sentigent/memory_{agent}.db")
    )
    rep = health_report(MemoryStore(agent_id=agent, org_id=org, db_path=db_path))

    print(json.dumps(rep, indent=2))
    print(f"\n{'✅ healthy' if rep['ok'] else '⚠ needs attention'} — "
          f"{rep['precedents']} precedents · {rep['calibration_events']} calibration events · "
          f"{rep['answered_escalations']} answered / {rep['open_escalations']} open escalations")
    for w in rep["warnings"]:
        print(f"  ⚠ {w}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
