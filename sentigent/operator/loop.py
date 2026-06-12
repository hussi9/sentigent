"""LoopRunner — the Ralph/dark-factory outer loop around operate().

operate() is a single linear pass over a plan. run_loop() wraps it into the loop
that loop-engineering is about: each lap runs a FRESH worker (clean context — the
agent forgets, the repo + DB remember) over a (re-derived) plan, then asks the
goal-level GoalDoD "is the whole objective done?". It keeps lapping until the goal
is satisfied, a human is genuinely needed, or a hard stop (kill/budget/max-laps).

The Clone Resolver inside operate() keeps the line running through soft blockers
(answering them AS the user); the loop only halts to `waiting` when the clone
couldn't resolve a blocker and a human must.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sentigent.operator.escalation import AUTOPILOT
from sentigent.operator.operate import operate
from sentigent.operator.resolver import CloneResolver
from sentigent.operator.runner import OperatorRunner


@dataclass
class LoopResult:
    status: str            # done | waiting | exhausted | killed | budget | handover | max_laps
    laps: int
    reason: str
    run_ids: list[int] = field(default_factory=list)
    clone_resolves: int = 0
    asks: int = 0

    @property
    def autonomy_rate(self) -> float:
        faced = self.clone_resolves + self.asks
        return (self.clone_resolves / faced) if faced else 1.0

    def to_dict(self) -> dict:
        return {
            "status": self.status, "laps": self.laps, "reason": self.reason,
            "run_ids": self.run_ids, "clone_resolves": self.clone_resolves,
            "asks": self.asks, "autonomy_rate": round(self.autonomy_rate, 3),
        }

    def digest(self) -> str:
        icon = {"done": "✅", "waiting": "⏸", "exhausted": "🟡", "killed": "🛑",
                "budget": "💰", "handover": "🤝", "max_laps": "🔁"}.get(self.status, "•")
        return (f"## Loop {icon} {self.status} after {self.laps} lap(s)\n"
                f"{self.reason}\n"
                f"clone-resolved {self.clone_resolves} blocker(s) · paged you {self.asks}× · "
                f"autonomy {self.autonomy_rate:.0%}")


def run_loop(
    store: Any,
    goal: str,
    dod: Any,                                   # GoalDoD (or any obj with .satisfied(repo))
    *,
    plan: Optional[Any] = None,
    plan_fn: Optional[Callable[[int], Any]] = None,   # lap -> Plan (re-derive each lap)
    repo_path: str = ".",
    runner_factory: Optional[Callable[[int], Any]] = None,  # lap -> fresh runner
    max_laps: int = 8,
    autonomy: str = AUTOPILOT,
    budget_usd: float = 2.0,
    execute: bool = False,
    resolver: Optional[CloneResolver] = None,
    resolver_thresholds: Optional[dict] = None,
    **operate_kwargs: Any,
) -> LoopResult:
    """Drive a goal to its GoalDoD across fresh-context laps. Never raises.

    Provide `plan` (fixed) OR `plan_fn(lap)` (re-derived each lap — the Ralph move).
    A fresh runner per lap is the clean-context discipline; pass `runner_factory`
    to control it (defaults to a new OperatorRunner per lap)."""
    run_ids: list[int] = []
    clone_resolves = 0
    asks = 0

    # Learn per-category thresholds from the override rate once at loop start, unless
    # the caller pinned them. This is the calibration feedback closing the loop.
    if resolver_thresholds is None:
        try:
            resolver_thresholds = CloneResolver.thresholds_from_calibration(store)
        except Exception:
            resolver_thresholds = None

    for lap in range(1, max_laps + 1):
        lap_plan = plan_fn(lap) if plan_fn else plan
        if lap_plan is None or not getattr(lap_plan, "pending", []):
            d = dod.satisfied(repo_path)
            status = "done" if d.satisfied else "exhausted"
            return LoopResult(status, lap - 1 if lap > 1 else 0,
                              d.reason if d.satisfied else "no more work but goal not met",
                              run_ids, clone_resolves, asks)

        runner = (runner_factory(lap) if runner_factory
                  else OperatorRunner(dry_run=not execute))
        res = operate(
            store, lap_plan, autonomy=autonomy, budget_usd=budget_usd,
            execute=execute, runner=runner, repo_path=repo_path,
            resolver=resolver, resolver_thresholds=resolver_thresholds,
            **operate_kwargs,
        )
        run_ids.append(res.run_id)
        clone_resolves += res.clone_resolves
        asks += res.asks

        if res.status == "killed":
            return LoopResult("killed", lap, "kill switch tripped", run_ids, clone_resolves, asks)
        if res.status == "budget_exhausted":
            return LoopResult("budget", lap, "budget exhausted", run_ids, clone_resolves, asks)
        if res.status == "handover":
            return LoopResult("handover", lap, "you took over the worktree", run_ids, clone_resolves, asks)
        if res.status == "waiting":
            # The clone couldn't resolve a blocker — a human is genuinely needed.
            return LoopResult("waiting", lap,
                              f"blocked: escalation #{res.open_escalation_id} needs you",
                              run_ids, clone_resolves, asks)

        # Lap completed its plan. Is the whole objective done?
        d = dod.satisfied(repo_path)
        if d.satisfied:
            return LoopResult("done", lap, d.reason, run_ids, clone_resolves, asks)
        # Not done → next lap re-derives (if plan_fn) or, with a fixed plan whose
        # steps are now all done, the next lap finds nothing pending → exhausted.

    return LoopResult("max_laps", max_laps, f"hit max_laps ({max_laps}) before goal done",
                      run_ids, clone_resolves, asks)
