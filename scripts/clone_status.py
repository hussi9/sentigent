#!/usr/bin/env python3
"""clone_status.py — the Clone Readiness gauge.

How much of YOU is captured into the clone, as a live %, with the one next move
that raises it most. Run it any time to watch the number climb.

    python3 scripts/clone_status.py
    python3 scripts/clone_status.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.config import get_config  # noqa: E402
from sentigent.core import clone_readiness  # noqa: E402
from sentigent.memory.store import MemoryStore  # noqa: E402

_cfg = get_config()
AGENT = os.environ.get("SENTIGENT_AGENT_ID", _cfg.agent_id)
ORG = os.environ.get("SENTIGENT_ORG_ID", _cfg.org_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="Show how much of you the clone has captured.")
    ap.add_argument("--agent", default=AGENT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    store = MemoryStore(agent_id=args.agent, org_id=ORG)
    r = clone_readiness.compute(store)

    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    bar = clone_readiness.render_bar(r.percent)
    print()
    print(f"  🧬  CLONE READINESS   {r.percent}%")
    print(f"      {bar}")
    print(f"      {r.stage}")
    print()
    print("  Captured from:")
    for c in r.components:
        cbar = clone_readiness.render_bar(int(round(c.pct * 100)), width=12)
        print(f"    {cbar}  {c.earned:>4.1f}/{c.weight:<2}  {c.key:<20} {c.detail}")
    print()
    print(f"  ➜  Next, to grow the clone: {r.next_action}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
