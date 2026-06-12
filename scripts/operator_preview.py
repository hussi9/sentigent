#!/usr/bin/env python3
"""operator_preview.py — watch the Operator judge a plan AS you (dry-run).

Give it any plan (markdown task list). For each step it shows what it WOULD do —
proceed, auto-correct, or wake you — with the risk floor and its reasoning in your
voice. Nothing executes. This is the brain made visible.

    python3 scripts/operator_preview.py examples/sample-plan.md
    python3 scripts/operator_preview.py myplan.md --autonomy autopilot
    python3 scripts/operator_preview.py --goal "ship the dark-mode toggle"   # one-line goal
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.core import clone_readiness  # noqa: E402
from sentigent.memory.store import MemoryStore  # noqa: E402
from sentigent.operator.escalation import ASSISTED, COPILOT, AUTOPILOT, TRUSTED  # noqa: E402
from sentigent.operator.plan import parse_plan, parse_plan_file  # noqa: E402
from sentigent.operator.preview import preview_plan  # noqa: E402

AGENT = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
ORG = os.environ.get("SENTIGENT_ORG_ID", "hussain")

_DEC_ICON = {"continue": "✅", "correct": "✏️ ", "escalate": "🔔"}
_ASK_ICON = {True: "🔔 ASK YOU", False: "▶  auto"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Dry-run the Operator over a plan.")
    ap.add_argument("plan", nargs="?", help="path to a markdown plan file")
    ap.add_argument("--goal", help="a one-line goal instead of a file")
    ap.add_argument("--autonomy", default=ASSISTED,
                    choices=[COPILOT, ASSISTED, AUTOPILOT, TRUSTED])
    ap.add_argument("--agent", default=AGENT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.plan:
        plan = parse_plan_file(args.plan)
    elif args.goal:
        plan = parse_plan(f"- {args.goal}", goal=args.goal)
    else:
        ap.error("give a plan file or --goal")

    if not plan.pending:
        print("No pending steps found in that plan.")
        return 0

    store = MemoryStore(agent_id=args.agent, org_id=ORG)
    result = preview_plan(store, plan, autonomy=args.autonomy)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    rd = result.readiness
    print()
    print(f"  🧬 Clone readiness {rd['percent']}%  "
          f"{clone_readiness.render_bar(rd['percent'], 16)}   (profile: {result.profile_source})")
    print(f"  🎯 {result.goal}")
    print(f"  🎚  autonomy: {result.autonomy}")
    print("  " + "─" * 70)

    for r in result.reviews:
        v, e, risk = r.verdict, r.escalation, r.risk
        icon = _DEC_ICON.get(v.decision, "•")
        risk_tag = f"risk:{risk.level}" + ("⛔" if risk.policy_wall else "")
        print(f"  {r.step.idx:>2}. {icon} {_ASK_ICON[e.ask]:<10} [{risk_tag:<12}] {r.step.description[:60]}")
        if v.reason:
            print(f"        ↳ {v.reason}  (conf {v.confidence:.0%}, {v.source})")
        if v.decision == 'correct' and v.correction:
            print(f"        ✏️  would fix: {v.correction}")
        if e.ask:
            print(f"        🔔 {e.headline}")

    print("  " + "─" * 70)
    print(f"  Σ  {result.auto} auto-proceed · {result.asks} would ask you · "
          f"longest unattended run: {result.longest_unattended_run} steps")
    print(f"  ➜  grow the clone: {rd['next_action']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
