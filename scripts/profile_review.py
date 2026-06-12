#!/usr/bin/env python3
"""profile_review.py — Step 2: review your clone (the good, the bad, the gaps).

Benchmarks your profile + practices against universal (and any org) best practices
and shows what to keep, what to fix, and what to add. Adopt a suggestion straight
into your playbook to improve the clone (Step 3).

    python3 scripts/profile_review.py                 # full review
    python3 scripts/profile_review.py --adopt 3       # adopt gap #3 as a practice
    python3 scripts/profile_review.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.core import clone_readiness, profile_review  # noqa: E402
from sentigent.memory.store import MemoryStore  # noqa: E402

AGENT = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
ORG = os.environ.get("SENTIGENT_ORG_ID", "hussain")


def main() -> int:
    ap = argparse.ArgumentParser(description="Review your clone against best practices.")
    ap.add_argument("--agent", default=AGENT)
    ap.add_argument("--adopt", type=int, metavar="N", help="adopt gap #N as a practice")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    store = MemoryStore(agent_id=args.agent, org_id=ORG)
    r = profile_review.review(store)

    if args.adopt is not None:
        if not (1 <= args.adopt <= len(r.gaps)):
            print(f"No gap #{args.adopt}. There are {len(r.gaps)} gaps.")
            return 1
        g = r.gaps[args.adopt - 1]
        pid = store.add_practice(g.statement, domain=g.domain, cadence=g.cadence)
        print(f"✓ adopted into your playbook (practice #{pid}): [{g.cadence}/{g.domain}] {g.statement}")
        print(f"  why: {g.rationale}")
        print("  → re-run clone_status.py / profile_review.py to see the clone improve.")
        return 0

    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    bar = clone_readiness.render_bar(r.coverage_pct)
    print()
    print(f"  📋  CLONE REVIEW   best-practice coverage {r.coverage_pct}%")
    print(f"      {bar}   (profile: {r.profile_source}, analysis: {r.source})")
    print()

    if r.good:
        print("  ✅ THE GOOD — keep doing these:")
        for i in r.good[:8]:
            why = f"  — {i.why}" if i.why else ""
            print(f"     • {i.text}{why}")
        print()
    if r.bad:
        print("  ⚠️  THE BAD — tensions to watch:")
        for i in r.bad[:6]:
            why = f"  — {i.why}" if i.why else ""
            print(f"     • {i.text}{why}")
        print()
    if r.gaps:
        print("  ➕ MISSING — suggestions you can adopt (profile_review.py --adopt N):")
        for n, g in enumerate(r.gaps[:10], 1):
            star = "‼️" if g.importance == "high" else "  "
            print(f"   {star}{n:>2}. [{g.domain}] {g.statement}")
            print(f"          {g.rationale}")
        print()
    print("  ➜  adopt the most important gaps to raise coverage and grow your clone.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
