"""Batch N-trial toy-harness ablation: A0 (one-shot) vs A2 (raw bounded
repair) vs A3 (judge-gated repair), exercising the REAL, live
``sentigent.core.engine.Sentigent`` judge for A3 — not a stub.

## Why this exists

The A0/A2 toy-harness numbers already in this codebase's history (and the
real 17-task SWE-bench pilot cited in ``docs/EVALUATION.md``) measure a
generic verify-then-repair loop. They never import or call
``sentigent.core.engine.Sentigent`` — so they cannot support any claim that
Sentigent's *judgment* (as opposed to "retry on failure") changes outcomes.
A3 (:func:`sentigent.eval.ablation.arms.run_arm_a3`) closes that gap: it
consults a judge on every hidden-test failure and only spends a repair lap on
a non-PROCEED verdict. This module runs A0/A2/A3 side by side, N times, with
a REAL live judge instance wired into A3.

## Honesty about what this is (and isn't)

This is a CONTROLLED SYNTHETIC harness, not a re-run of real SWE-bench
execution. The underlying toy fixture (``sentigent.eval.ablation.task``) is
the deliberately-broken ``add()`` function used throughout this harness's
existing tests. Since that single fixture is trivially and deterministically
solvable, running it N times unmodified would produce a ceiling artifact
(100% resolved on first try, every time — uninformative, matching the exact
failure mode already documented for the real "Pilot 1" 3-task SWE-bench
sample in the private dev repo's WSB-REAL-FINDINGS.md).

To get a stable, non-degenerate ratio, each of the N trials draws (once, from
a seeded RNG) whether the solver's FIRST patch is correct and, if not,
whether a REPAIR patch (given failure feedback) would be correct. These two
Bernoulli rates are calibrated to mirror the empirically observed rates from
the real 17-task SWE-bench Pilot 2 already in this repo's EVALUATION.md
(first-pass 9/17 ≈ 53%; repair-success-among-first-failures 4/8 = 50%) so the
synthetic distribution is realistic rather than arbitrary — but it is still
synthetic, and is reported as such. The SAME per-trial draw is reused across
all three arms so A0/A2/A3 differ only in POLICY (whether/when a repair lap
is spent), never in which underlying task realization they see — this
isolates the repair-gating mechanism from sampling noise.

Usage::

    python -m sentigent.eval.ablation.toy_batch --n 50 --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
from dataclasses import dataclass, field

from sentigent.core.engine import Sentigent
from sentigent.eval.ablation.arms import run_arm_a0, run_arm_a2, run_arm_a3
from sentigent.eval.ablation.solver import MockSolver
from sentigent.eval.ablation.task import build_toy_task

_GOOD_PATCH = '''"""Toy module under test (patched)."""


def add(a, b):
    return a + b
'''

# Two distinct "still wrong" patches so the harness never accidentally
# reuses the good patch text for a scripted failure.
_WRONG_FIRST = '''"""Toy module under test (deliberately broken, take 2)."""


def add(a, b):
    return a - b
'''

_WRONG_REPAIR = '''"""Toy module under test (still wrong after "repair")."""


def add(a, b):
    return a * b
'''

# Calibrated to the real 17-task SWE-bench Pilot 2 numbers already cited in
# docs/EVALUATION.md: A0 resolved 9/17 (53%); of the 8 A0 failures, A2's
# bounded repair flipped 4 (50%) to passing.
DEFAULT_P_FIRST_OK = 9 / 17
DEFAULT_P_REPAIR_OK = 4 / 8


@dataclass
class TrialDraw:
    trial_id: int
    first_ok: bool
    repair_ok: bool


@dataclass
class ArmSummary:
    arm: str
    resolved: int = 0
    attempts_total: int = 0
    repaired: int = 0
    n: int = 0
    judge_repair_laps_spent: int = 0
    judge_repair_laps_skipped: int = 0

    def add(self, resolved: bool, attempts: int, repaired: bool) -> None:
        self.n += 1
        self.resolved += int(resolved)
        self.attempts_total += attempts
        self.repaired += int(repaired)

    @property
    def resolved_rate(self) -> float:
        return self.resolved / self.n if self.n else 0.0

    @property
    def avg_attempts(self) -> float:
        return self.attempts_total / self.n if self.n else 0.0

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "n": self.n,
            "resolved": self.resolved,
            "resolved_rate": round(self.resolved_rate, 4),
            "avg_attempts": round(self.avg_attempts, 4),
            "repaired": self.repaired,
        }


def _draw_trials(n: int, seed: int, p_first_ok: float, p_repair_ok: float) -> list[TrialDraw]:
    rng = random.Random(seed)
    trials = []
    for i in range(n):
        first_ok = rng.random() < p_first_ok
        repair_ok = rng.random() < p_repair_ok
        trials.append(TrialDraw(trial_id=i, first_ok=first_ok, repair_ok=repair_ok))
    return trials


def _solver_for(trial: TrialDraw) -> MockSolver:
    first = _GOOD_PATCH if trial.first_ok else _WRONG_FIRST
    repair = _GOOD_PATCH if trial.repair_ok else _WRONG_REPAIR
    return MockSolver([first, repair])


def run_batch(
    n: int = 50,
    seed: int = 42,
    p_first_ok: float = DEFAULT_P_FIRST_OK,
    p_repair_ok: float = DEFAULT_P_REPAIR_OK,
    judge_db_path: str | None = None,
) -> dict:
    """Run N paired trials through A0, A2, and A3 (live judge). Returns a report dict."""
    trials = _draw_trials(n, seed, p_first_ok, p_repair_ok)

    # Isolated judge DB — never memory_hussain.db, never the default
    # ~/.sentigent/memory.db. Fresh per run so the judge starts with no
    # learned bias from prior sessions.
    db_path = judge_db_path or os.path.join(
        tempfile.mkdtemp(prefix="sentigent_ablation_judge_"), "judge.db"
    )
    judge = Sentigent(
        profile="code_review",
        agent_id="ablation-a3-toy",
        org_id="ablation-eval",
        db_path=db_path,
    )

    a0 = ArmSummary(arm="A0")
    a2 = ArmSummary(arm="A2")
    a3 = ArmSummary(arm="A3")

    base_task = build_toy_task()

    for trial in trials:
        r0 = run_arm_a0(base_task, _solver_for(trial))
        a0.add(r0.resolved, r0.attempts, r0.repaired)

        r2 = run_arm_a2(base_task, _solver_for(trial))
        a2.add(r2.resolved, r2.attempts, r2.repaired)

        r3 = run_arm_a3(base_task, _solver_for(trial), judge)
        a3.add(r3.resolved, r3.attempts, r3.repaired)
        if r3.attempts > 1:
            a3.judge_repair_laps_spent += 1
        elif not trial.first_ok:
            # First attempt failed but A3 never spent a repair lap ->
            # the judge gated it out (PROCEED verdict).
            a3.judge_repair_laps_skipped += 1

    report = {
        "n": n,
        "seed": seed,
        "p_first_ok_input": p_first_ok,
        "p_repair_ok_input": p_repair_ok,
        "judge_db_path": db_path,
        "judge_graded_score": judge.graded_judgment_score,
        "arms": {
            "A0": a0.to_dict(),
            "A2": a2.to_dict(),
            "A3": {
                **a3.to_dict(),
                "judge_repair_laps_spent": a3.judge_repair_laps_spent,
                "judge_repair_laps_skipped": a3.judge_repair_laps_skipped,
            },
        },
        "delta_a3_minus_a2_pts": round(
            (a3.resolved_rate - a2.resolved_rate) * 100, 2
        ),
    }
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="toy_batch")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--p-first-ok", type=float, default=DEFAULT_P_FIRST_OK)
    p.add_argument("--p-repair-ok", type=float, default=DEFAULT_P_REPAIR_OK)
    args = p.parse_args()
    result = run_batch(
        n=args.n, seed=args.seed,
        p_first_ok=args.p_first_ok, p_repair_ok=args.p_repair_ok,
    )
    print(json.dumps(result, indent=2))
