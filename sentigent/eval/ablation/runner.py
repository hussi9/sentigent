"""Paired arm runner for the WS-B CORE ablation harness.

Runs the SAME logical toy task through BOTH arms (A0 then A2), each on its own
fresh task copy and its own fresh solver, and appends ONE result row per arm to
a sprint-scoped :class:`~sentigent.eval.ablation.results_db.AblationResultsDB`.

The arms are independent: ``task_builder`` builds a fresh task copy and
``solver_factory`` mints a fresh solver for each arm, so neither the task state
nor the solver's call counter leaks between arms.

See docs/TRUTH-SPRINT-2WEEK.md (Workstream WS-B). Additive only.
"""

from __future__ import annotations

from typing import Callable

from sentigent.eval.ablation.arms import ArmResult, run_arm_a0, run_arm_a2
from sentigent.eval.ablation.results_db import AblationResultsDB
from sentigent.eval.ablation.solver import Solver
from sentigent.eval.ablation.task import AblationTask, build_toy_task


def run_paired(
    solver_factory: Callable[[], Solver],
    db: AblationResultsDB,
    task_builder: Callable[[], AblationTask] = build_toy_task,
) -> list[ArmResult]:
    """Run the same logical task through both arms and record one row each.

    Args:
        solver_factory: zero-arg callable that mints a FRESH solver per arm, so
            each arm gets an independent solver (and call counter).
        db: the sprint-scoped results DB to append rows into. NEVER the operator
            brain — :class:`AblationResultsDB` enforces that isolation.
        task_builder: zero-arg callable that builds a fresh task copy per arm.

    Returns:
        ``[a0_result, a2_result]`` — the two :class:`ArmResult` objects, in the
        same order their rows are appended to ``db``.
    """
    a0_task = task_builder()
    a0_result = run_arm_a0(a0_task, solver_factory())
    db.append_result(
        task_id=a0_task.task_id,
        arm="A0",
        resolved=a0_result.resolved,
        attempts=a0_result.attempts,
        repaired=a0_result.repaired,
    )

    a2_task = task_builder()
    a2_result = run_arm_a2(a2_task, solver_factory())
    db.append_result(
        task_id=a2_task.task_id,
        arm="A2",
        resolved=a2_result.resolved,
        attempts=a2_result.attempts,
        repaired=a2_result.repaired,
    )

    return [a0_result, a2_result]
