"""Reconcile skill-router follow/ignore signal into routing_seeds.outcome.

The companion to ``migrate_skill_router_data`` (which imports routing DECISIONS):
this closes the loop by importing the downstream OUTCOME — whether each routed
prompt's chosen skill was actually invoked — and writing it back to
``routing_seeds.outcome``, the field ``sentigent.routing.matcher`` respects.

Run periodically (cron / launchd) to keep the embedding router self-correcting:

    .venv/bin/python -m sentigent.scripts.reconcile_routing_outcomes
    .venv/bin/python -m sentigent.scripts.reconcile_routing_outcomes --dry-run
    .venv/bin/python -m sentigent.scripts.reconcile_routing_outcomes --days 30

Idempotent: re-running only writes seeds whose verdict changed.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from sentigent.routing import reconciler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile skill-router outcomes into Sentigent routing_seeds"
    )
    parser.add_argument("--router-log", default=str(reconciler.ROUTER_LOG_DEFAULT),
                        help="Path to skill_router_log.jsonl")
    parser.add_argument("--usage-log", default=str(reconciler.USAGE_LOG_DEFAULT),
                        help="Path to skill_usage.log")
    parser.add_argument("--agent", default="default", help="Agent ID for MemoryStore")
    parser.add_argument("--org", default="default", help="Org ID for MemoryStore")
    parser.add_argument("--days", type=int, default=0,
                        help="Only consider events from the last N days (0 = all history)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args()

    since = (time.time() - args.days * 86400) if args.days > 0 else 0.0
    router_log = Path(args.router_log)
    usage_log = Path(args.usage_log)

    routes = reconciler.parse_route_events(router_log, since=since)
    invs = reconciler.parse_invocations(usage_log, since=since)
    print(f"Parsed {len(routes)} route events, {len(invs)} skill invocations"
          f"{f' (last {args.days}d)' if args.days else ''}.")

    if args.dry_run:
        # Compute the tally + verdicts without touching the store.
        tallies: dict[str, list] = {}
        for r in routes:
            pair = tallies.setdefault(r["prompt_hash"], [0, 0, r["skill"]])
            pair[1] += 1
            if reconciler._was_followed(r, invs):
                pair[0] += 1
        demote = reinforce = thin = 0
        for h, (followed, total, skill) in sorted(tallies.items()):
            verdict = reconciler.classify(followed, total)
            if verdict == "incorrect":
                demote += 1
                print(f"  DEMOTE     {h[:12]}  {skill:<32} followed {followed}/{total}")
            elif verdict == "correct":
                reinforce += 1
                print(f"  REINFORCE  {h[:12]}  {skill:<32} followed {followed}/{total}")
            else:
                thin += 1
        print(f"\nDry run: {reinforce} would reinforce, {demote} would demote, "
              f"{thin} thin/unchanged across {len(tallies)} distinct prompts.")
        print("(dry-run — nothing written)")
        return

    from sentigent.memory.store import MemoryStore
    store = MemoryStore(agent_id=args.agent, org_id=args.org)
    stats = reconciler.reconcile_outcomes(store, routes, invs)
    print(f"Reconciled: {stats['reinforced']} reinforced, {stats['demoted']} demoted, "
          f"{stats['unchanged']} unchanged, {stats['unknown']} unknown "
          f"(of {stats['seen']} distinct routed prompts).")


if __name__ == "__main__":
    main()
