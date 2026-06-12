#!/usr/bin/env python3
"""learn.py — run the Sentigent learning loop (G2/G3) and report.

Closes the loop: turns the user's answered escalations + their reverts into
calibration events, surfaces drift, proposes a guarding practice, and — when the
signal is strong — writes a new operator_profile version with tightened
'ask_when' rules. Each run makes the next run need the user less.

    python3 scripts/learn.py            # run the loop, print a readable report
    python3 scripts/learn.py --show     # just show current per-domain calibration
    python3 scripts/learn.py --agent hussain --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.core.confidence_calibrator import ConfidenceCalibrator  # noqa: E402
from sentigent.core.profile_learner import ProfileLearner  # noqa: E402
from sentigent.memory.store import MemoryStore  # noqa: E402

AGENT = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
ORG = os.environ.get("SENTIGENT_ORG_ID", "hussain")


def _print_calibration(calib: ConfidenceCalibrator) -> None:
    rows = calib.calibrate()
    print()
    print("  📊  PER-DOMAIN CALIBRATION  (when confident, was it right?)")
    if not rows:
        print("      (no calibration signal yet — run some operator steps first)")
        print()
        return
    for dc in rows:
        pct = int(round(dc.rate * 100))
        print(f"    {dc.domain:<16} {dc.correct:>3}/{dc.total:<3} ({pct:>3}%)  "
              f"→ {dc.recommended_autonomy}")
        print(f"        {dc.rationale}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Sentigent learning loop.")
    ap.add_argument("--agent", default=AGENT)
    ap.add_argument("--show", action="store_true",
                    help="show current calibration without learning")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    store = MemoryStore(agent_id=args.agent, org_id=ORG)

    if args.show:
        calib = ConfidenceCalibrator(store)
        if args.json:
            print(json.dumps(calib.to_dict(), indent=2))
            return 0
        _print_calibration(calib)
        return 0

    learner = ProfileLearner(store)
    result = learner.learn()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print()
    print("  🔁  SENTIGENT LEARNING LOOP")
    print(f"      calibration events recorded:  {result.calibration_recorded}")
    print()
    if result.drift_signals:
        print("  ⚠️   Drift signals:")
        for d in result.drift_signals:
            print(f"      • {d}")
    else:
        print("  ✅  No drift — the clone is tracking you.")
    print()
    if result.proposed_practice:
        print(f"  💡  Proposed practice: {result.proposed_practice}")
        print()
    print("  🎚️   Recommended autonomy per domain:")
    if result.autonomy_recommendations:
        for domain, level in sorted(result.autonomy_recommendations.items()):
            print(f"      {domain:<16} → {level}")
    else:
        print("      (none yet)")
    print()
    if result.profile_version >= 0:
        print(f"  🧬  New operator_profile version written: v{result.profile_version}")
    else:
        print("  🧬  No new profile version (no meaningful new signal).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
