"""A3 arm — the judge-in-the-loop ablation.

Closes the 2026-07-07 principal review gap: A0/A2 never imported or exercised
the Sentigent judge, so the flagship "+24pts" result measured a generic
verify→repair loop, not the judgment engine. A3 is A2's repair loop, but each
repair lap is spent ONLY when the judge returns a non-proceed verdict on the
failing patch, and every lap's outcome is recorded back so the judge's own
accounting is exercised.
"""
from __future__ import annotations

from sentigent.eval.ablation.arms import run_arm_a3
from sentigent.eval.ablation.solver import MockSolver
from sentigent.eval.ablation.task import build_toy_task

_GOOD_PATCH = '''"""Toy module under test (patched)."""


def add(a, b):
    return a + b
'''

_WRONG_PATCH = '''"""Toy module under test (still wrong)."""


def add(a, b):
    return a * b
'''


class _StubDecision:
    def __init__(self, action: str):
        self.action = action
        self.trace_id = "trace-stub"


class _StubJudge:
    """Minimal judge: returns a fixed verdict, records every outcome call."""

    def __init__(self, action: str):
        self._action = action
        self.outcomes: list[str] = []

    def evaluate(self, task: str, context: dict) -> _StubDecision:
        return _StubDecision(self._action)

    def record_outcome(self, trace_id: str, outcome: str, feedback=None) -> None:
        self.outcomes.append(outcome)


def test_a3_repairs_when_judge_says_non_proceed():
    task = build_toy_task()
    solver = MockSolver([_WRONG_PATCH, _GOOD_PATCH])
    judge = _StubJudge("enrich")  # non-proceed -> spend a repair lap

    result = run_arm_a3(task, solver, judge)

    assert result.resolved is True
    assert result.attempts == 2
    assert result.repaired is True
    # One outcome recorded for the repair lap that flipped fail->pass.
    assert judge.outcomes == ["correct"]


def test_a3_stops_when_judge_says_proceed():
    task = build_toy_task()
    solver = MockSolver([_WRONG_PATCH, _GOOD_PATCH])
    judge = _StubJudge("proceed")  # judge declines to spend a repair

    result = run_arm_a3(task, solver, judge)

    assert result.resolved is False
    assert result.attempts == 1
    assert result.repaired is False
    assert solver.calls == 1  # never re-solved
    assert judge.outcomes == []  # no repair lap -> no outcome recorded


def test_a3_records_incorrect_when_repair_fails():
    task = build_toy_task()
    solver = MockSolver([_WRONG_PATCH, _WRONG_PATCH])  # repair also wrong
    judge = _StubJudge("slow_down")

    result = run_arm_a3(task, solver, judge)

    assert result.resolved is False
    assert result.attempts == 2
    assert result.repaired is False
    assert judge.outcomes == ["incorrect"]


def test_a3_first_patch_passes_no_judge_consult():
    task = build_toy_task()
    solver = MockSolver([_GOOD_PATCH])
    judge = _StubJudge("escalate")

    result = run_arm_a3(task, solver, judge)

    assert result.resolved is True
    assert result.attempts == 1
    assert result.repaired is False
    assert judge.outcomes == []  # never failed -> judge never consulted
