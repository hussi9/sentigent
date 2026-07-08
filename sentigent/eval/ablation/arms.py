"""Arm runners for the WS-B CORE ablation harness.

Each "arm" is a strategy for solving an :class:`AblationTask` with a pluggable
:class:`~sentigent.eval.ablation.solver.Solver`. Two arms ship here, mirroring
the loop_driver verify+repair concept:

  - ``A0`` (:func:`run_arm_a0`) — one-shot: solve once, apply, score against the
    hidden test. NO repair. ``attempts`` is always 1 and ``repaired`` always
    False.
  - ``A1`` (:func:`run_arm_a1`) — verify-then-single-revise control: same first
    attempt as A0, but on hidden-test FAILURE do EXACTLY ONE corrective
    regeneration with the failure feedback, re-apply, re-score, then STOP. A hard
    cap of one revision (NOT a loop), so the solver is called at most twice and
    ``attempts`` is 1 (first patch passed) or 2 (one revision happened).
    ``repaired`` stays False always — ``repaired`` is reserved for A2's iterative
    repair loop. A1 isolates "does a single failure-driven revision help" apart
    from A2's bounded multi-lap repair.
  - ``A2`` (:func:`run_arm_a2`) — same first attempt, but on hidden-test FAILURE
    do a bounded repair retry: solve again with the failure feedback, re-apply,
    re-score. ``repaired`` is True only if a repair lap flipped fail -> pass.

Every arm rebuilds a fresh toy task copy so arms never contaminate each other.

See docs/TRUTH-SPRINT-2WEEK.md (Workstream WS-B). Additive only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sentigent.eval.ablation.solver import Solver
from sentigent.eval.ablation.task import (
    AblationTask,
    apply_patch,
    build_toy_task,
    run_hidden_test,
)


@dataclass
class ArmResult:
    """Outcome of running one arm against a task.

    Attributes:
        resolved: True iff the hidden test passes after the arm's work.
        attempts: number of solve+apply+score laps performed (>= 1).
        repaired: True iff a repair lap flipped a failing result to passing.
    """

    resolved: bool
    attempts: int
    repaired: bool


def _fresh_task(task: AblationTask) -> AblationTask:
    """Rebuild a fresh toy task copy so arms don't contaminate each other."""
    return build_toy_task()


def _score(
    task: AblationTask, scorer: Callable[[AblationTask], bool] | None
) -> bool:
    """Score a task: use the injected ``scorer`` if given, else the toy hidden test.

    This is the single seam every arm routes through. When ``scorer`` is None the
    behavior is byte-for-byte identical to calling :func:`run_hidden_test`.
    """
    if scorer is not None:
        return scorer(task)
    return run_hidden_test(task)


# Failure feedback handed to the solver on every repair/revise lap (A1/A2/A3).
_REPAIR_FEEDBACK = (
    "The hidden test still fails after the previous patch. "
    "Return the full corrected file contents."
)


def _repair_lap(
    fresh: AblationTask,
    solver: Solver,
    scorer: Callable[[AblationTask], bool] | None,
) -> bool:
    """One repair lap: re-solve with failure feedback, apply, re-score.

    The shared body of A1's single revision and A2/A3's bounded repair loop, so
    a change to the repair mechanism can't silently drift between arms.
    """
    patch = solver.solve(fresh, feedback=_REPAIR_FEEDBACK)
    apply_patch(fresh, patch)
    return _score(fresh, scorer)


def run_arm_a0(
    task: AblationTask,
    solver: Solver,
    scorer: Callable[[AblationTask], bool] | None = None,
) -> ArmResult:
    """A0 arm: one-shot patch attempt with NO repair.

    Rebuilds a fresh task copy, solves once, applies the patch, and scores it.
    When ``scorer`` is provided it is used in place of the toy hidden test;
    otherwise behavior is unchanged. ``attempts`` is always 1; ``repaired``
    always False.
    """
    fresh = _fresh_task(task)
    patch = solver.solve(fresh)
    apply_patch(fresh, patch)
    resolved = _score(fresh, scorer)
    return ArmResult(resolved=resolved, attempts=1, repaired=False)


def run_arm_a1(
    task: AblationTask,
    solver: Solver,
    scorer: Callable[[AblationTask], bool] | None = None,
) -> ArmResult:
    """A1 arm: verify-then-single-revise control (hard cap of one revision).

    Rebuilds a fresh task copy and runs the same first attempt as A0. On
    hidden-test FAILURE it does EXACTLY ONE corrective regeneration with the
    failure feedback (solve again, re-apply, re-score), then STOPS — a hard cap,
    NOT a loop, so the solver is called at most twice. ``attempts`` is 1 when the
    first patch passes and 2 when a single revision happens. ``repaired`` is
    always False — that flag is reserved for A2's iterative repair loop.
    """
    fresh = _fresh_task(task)
    patch = solver.solve(fresh)
    apply_patch(fresh, patch)
    resolved = _score(fresh, scorer)
    attempts = 1

    if not resolved:
        resolved = _repair_lap(fresh, solver, scorer)
        attempts = 2

    return ArmResult(resolved=resolved, attempts=attempts, repaired=False)


def run_arm_a2(
    task: AblationTask,
    solver: Solver,
    max_repairs: int = 1,
    scorer: Callable[[AblationTask], bool] | None = None,
) -> ArmResult:
    """A2 arm: one-shot attempt plus a bounded repair retry on failure.

    Rebuilds a fresh task copy and runs the same first attempt as A0. On
    hidden-test FAILURE it does up to ``max_repairs`` repair laps: solve again
    with failure feedback, re-apply, re-score. ``repaired`` is True only if a
    repair lap flipped a failing result to passing.
    """
    fresh = _fresh_task(task)
    patch = solver.solve(fresh)
    apply_patch(fresh, patch)
    resolved = _score(fresh, scorer)
    attempts = 1
    repaired = False

    repairs = 0
    while not resolved and repairs < max_repairs:
        resolved = _repair_lap(fresh, solver, scorer)
        attempts += 1
        repairs += 1
        if resolved:
            repaired = True

    return ArmResult(resolved=resolved, attempts=attempts, repaired=repaired)


def _proceed(decision) -> bool:
    """True iff a judge decision is a PROCEED verdict (skip the repair lap)."""
    action = getattr(decision, "action", decision)
    return getattr(action, "value", action) == "proceed"


def run_arm_a3(
    task: AblationTask,
    solver: Solver,
    judge,
    max_repairs: int = 1,
    scorer: Callable[[AblationTask], bool] | None = None,
) -> ArmResult:
    """A3 arm: A2's repair loop, but each repair is GATED BY THE JUDGE.

    This is the only arm that exercises the Sentigent judgment engine — A0/A2
    never touch it (see docs/WSB-REAL-FINDINGS.md). Same first attempt as A0.
    On hidden-test FAILURE, the judge is consulted on the failing patch: only a
    NON-proceed verdict spends a repair lap (solve again with feedback, re-apply,
    re-score). Each repair lap's result is recorded back via
    ``judge.record_outcome`` — 'correct' if it flipped fail->pass, else
    'incorrect' — so the judge's own accounting sees real graded outcomes.

    Args:
        judge: a Sentigent-like object exposing ``evaluate(task, context)`` ->
            a decision with ``.action`` and ``.trace_id``, and
            ``record_outcome(trace_id, outcome)``.
    """
    fresh = _fresh_task(task)
    patch = solver.solve(fresh)
    apply_patch(fresh, patch)
    resolved = _score(fresh, scorer)
    attempts = 1
    repaired = False

    repairs = 0
    while not resolved and repairs < max_repairs:
        # Ask the judge whether this failing patch warrants a repair lap.
        decision = judge.evaluate(
            task="repair failing patch",
            context={
                "tool_name": "Edit",
                "tool_input": fresh.broken_file if hasattr(fresh, "broken_file") else "",
                "attempts": attempts,
                "hidden_test_failed": True,
            },
        )
        if _proceed(decision):
            # Judge says proceed (don't repair) — stop and let the failure stand.
            break

        feedback = (
            "The hidden test still fails after the previous patch. "
            "Return the full corrected file contents."
        )
        patch = solver.solve(fresh, feedback=feedback)
        apply_patch(fresh, patch)
        resolved = _score(fresh, scorer)
        attempts += 1
        repairs += 1
        if resolved:
            repaired = True

        # Record the graded outcome of this judge-authorized repair lap.
        try:
            judge.record_outcome(
                getattr(decision, "trace_id", ""),
                "correct" if resolved else "incorrect",
            )
        except Exception:
            pass

    return ArmResult(resolved=resolved, attempts=attempts, repaired=repaired)
