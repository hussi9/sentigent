"""Flywheel — the phase engine that turns the Loop into a full build cycle.

run_loop drives ONE goal to its definition-of-done. The flywheel chains the
canonical build phases into a self-advancing cycle, each phase its own goal+DoD
run through the loop, with a GATE between phases that decides advance / loop-back /
escalate. The steering meeting is the gate on the Plan phase (converge before
building); a failed review loops back to Plan; a finished phase advances. When the
last phase finishes, the cycle either ends or rolls into the next phase of work.

    Research → Brainstorm → ▶Steering◀ → Plan → Implement → Code-Review ─┐
        ▲                                                                 │
        └──────────────────── loop to the next phase ────────────────────┘

The flywheel is the deterministic spine. The *work* inside research/brainstorm/
steering is done by Claude-side agents+skills (see docs/superpowers/FLYWHEEL.md);
implement/review run real loops with the Clone Resolver keeping the line moving.
A gate is just a callable, so the steering-meeting verdict plugs straight in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sentigent.operator.escalation import AUTOPILOT
from sentigent.operator.loop import LoopResult, run_loop

# Gate decisions.
ADVANCE = "advance"      # phase converged → go to the next phase
LOOPBACK = "loopback"    # phase rejected → return to an earlier phase (re-derive)
ESCALATE = "escalate"    # a human is genuinely needed

# Canonical build phases (the flywheel order).
RESEARCH, BRAINSTORM, STEERING, PLAN, IMPLEMENT, REVIEW = (
    "research", "brainstorm", "steering", "plan", "implement", "review")
CANONICAL_ORDER = [RESEARCH, BRAINSTORM, STEERING, PLAN, IMPLEMENT, REVIEW]


@dataclass
class Phase:
    """One station of the flywheel. `dod` is any object with .satisfied(repo) →
    obj(.satisfied, .reason) (a GoalDoD or a stub). `gate` maps a finished phase to
    advance/loopback/escalate; default: loop-done→advance, waiting→escalate,
    else→loopback. `loopback_to` names where a loopback returns (default: previous)."""
    name: str
    goal: str
    dod: Any
    plan: Optional[Any] = None
    plan_fn: Optional[Callable[[int], Any]] = None
    gate: Optional[Callable[[LoopResult], tuple]] = None   # (LoopResult) -> (decision, reason)
    loopback_to: Optional[str] = None
    autonomy: str = AUTOPILOT


@dataclass
class PhaseRun:
    name: str
    loop_status: str
    decision: str
    reason: str
    laps: int
    autonomy_rate: float

    def to_dict(self) -> dict:
        return {"phase": self.name, "loop_status": self.loop_status,
                "decision": self.decision, "reason": self.reason,
                "laps": self.laps, "autonomy_rate": round(self.autonomy_rate, 3)}


@dataclass
class FlywheelResult:
    status: str                 # completed | escalated | max_cycles
    cycles: int
    history: list[PhaseRun] = field(default_factory=list)
    reason: str = ""

    @property
    def autonomy_rate(self) -> float:
        rates = [h.autonomy_rate for h in self.history]
        return (sum(rates) / len(rates)) if rates else 1.0

    def to_dict(self) -> dict:
        return {"status": self.status, "cycles": self.cycles, "reason": self.reason,
                "autonomy_rate": round(self.autonomy_rate, 3),
                "history": [h.to_dict() for h in self.history]}

    def digest(self) -> str:
        icon = {"completed": "✅", "escalated": "⏸", "max_cycles": "🔁"}.get(self.status, "•")
        lines = [f"## Flywheel {icon} {self.status} — {self.cycles} cycle(s) · "
                 f"avg autonomy {self.autonomy_rate:.0%}", self.reason or ""]
        for h in self.history:
            d = {"advance": "→", "loopback": "↩", "escalate": "⏸"}.get(h.decision, "·")
            lines.append(f"  {d} {h.name:<10} {h.loop_status:<9} "
                         f"{h.laps} lap(s) · {h.autonomy_rate:.0%} — {h.reason[:50]}")
        return "\n".join(lines)


def _default_gate(res: LoopResult) -> tuple:
    if res.status == "done":
        return (ADVANCE, "phase done")
    if res.status in ("waiting", "handover"):
        return (ESCALATE, res.reason)
    if res.status in ("killed", "budget"):
        return (ESCALATE, res.reason)
    return (LOOPBACK, res.reason)   # exhausted / max_laps → re-derive


def run_flywheel(
    store: Any,
    phases: list[Phase],
    *,
    repo_path: str = ".",
    max_cycles: int = 12,
    runner_factory: Optional[Callable[[int], Any]] = None,
    on_phase: Optional[Callable[[PhaseRun], None]] = None,
    **loop_kwargs: Any,
) -> FlywheelResult:
    """Drive the phases as a self-advancing cycle. Never raises.

    `max_cycles` bounds total phase executions (loop-backs included) so a phase that
    keeps failing its gate can't spin forever. `on_phase` is a progress callback."""
    by_name = {p.name: i for i, p in enumerate(phases)}
    history: list[PhaseRun] = []
    idx = 0
    cycles = 0

    while 0 <= idx < len(phases):
        if cycles >= max_cycles:
            return FlywheelResult("max_cycles", cycles, history,
                                  f"hit max_cycles ({max_cycles}) at phase "
                                  f"'{phases[idx].name}'")
        cycles += 1
        phase = phases[idx]
        res = run_loop(
            store, phase.goal, phase.dod, plan=phase.plan, plan_fn=phase.plan_fn,
            repo_path=repo_path, autonomy=phase.autonomy,
            runner_factory=runner_factory, **loop_kwargs,
        )
        decision, reason = (phase.gate or _default_gate)(res)
        run = PhaseRun(phase.name, res.status, decision, reason,
                       res.laps, res.autonomy_rate)
        history.append(run)
        if on_phase:
            try:
                on_phase(run)
            except Exception:
                pass

        if decision == ESCALATE:
            return FlywheelResult("escalated", cycles, history,
                                  f"phase '{phase.name}' needs you: {reason}")
        if decision == LOOPBACK:
            target = phase.loopback_to
            idx = by_name.get(target, idx - 1) if target else max(0, idx - 1)
            continue
        idx += 1   # ADVANCE

    return FlywheelResult("completed", cycles, history,
                          "all phases converged through the flywheel")
