#!/usr/bin/env python3
"""practice.py — your "how I build" playbook.

Declare the best practices you want held to (code review at milestones, tests
before commit). Each one (1) raises Clone Readiness, (2) the Operator judges your
work against, and (3) gets adherence-tracked from your real signal.

    python3 scripts/practice.py add "Run the full test suite before a milestone commit" --domain testing --cadence milestone
    python3 scripts/practice.py add "Self-review the diff before opening a PR" --domain review --cadence pr
    python3 scripts/practice.py list
    python3 scripts/practice.py off 3
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.memory.store import MemoryStore  # noqa: E402

AGENT = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
ORG = os.environ.get("SENTIGENT_ORG_ID", "hussain")
CADENCES = ("always", "commit", "milestone", "deploy", "pr")


def _store(agent: str) -> MemoryStore:
    return MemoryStore(agent_id=agent, org_id=ORG)


def _print_practice(p: dict) -> None:
    total = p["times_followed"] + p["times_skipped"]
    adh = f"{p['times_followed']}/{total} held" if total else "no checks yet"
    flag = "" if p["active"] else "  (inactive)"
    print(f"  #{p['id']:<3} [{p['cadence']}/{p['domain']}] {p['text']}  · {adh}{flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage your best-practices playbook.")
    ap.add_argument("--agent", default=AGENT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add a best practice")
    a.add_argument("text")
    a.add_argument("--domain", default="global")
    a.add_argument("--cadence", default="always", choices=CADENCES)

    sub.add_parser("list", help="list practices")
    off = sub.add_parser("off", help="deactivate a practice"); off.add_argument("id", type=int)
    on = sub.add_parser("on", help="reactivate a practice"); on.add_argument("id", type=int)

    args = ap.parse_args()
    store = _store(args.agent)

    if args.cmd == "add":
        pid = store.add_practice(args.text, domain=args.domain, cadence=args.cadence)
        print(f"✓ added practice #{pid}: [{args.cadence}/{args.domain}] {args.text}")
        print("  (raises clone readiness — check `clone_status.py`)")
        return 0
    if args.cmd == "list":
        rows = store.get_practices(active_only=False)
        if not rows:
            print("No practices yet. Add one:")
            print('  python3 scripts/practice.py add "Tests before commit" --domain testing --cadence commit')
            return 0
        print(f"\n  Your build playbook ({sum(1 for r in rows if r['active'])} active):")
        for p in rows:
            _print_practice(p)
        print()
        return 0
    if args.cmd in ("off", "on"):
        store.set_practice_active(args.id, args.cmd == "on")
        print(f"✓ practice #{args.id} {'reactivated' if args.cmd == 'on' else 'deactivated'}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
