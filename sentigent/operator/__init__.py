"""sentigent.operator — the autopilot that drives Claude Code AS you.

Phase 1 slice (dry-run judgment preview): given a plan and your operator
profile, the Operator judges each step the way YOU would — proceed, correct,
or wake you — and shows its reasoning. Nothing executes yet; this is the brain
made visible so you can watch it think as you before trusting it to act.

Layers (per docs/plans/2026-06-03-operator-autopilot-design.md):
  risk.py        D3/F3  RiskAssessor + PolicyWall hard floor
  plan.py        B1     PlanIngest — markdown plan → steps
  gate.py        D1     ProfileGate — would-you-approve verdict (local LLM)
  escalation.py  D4     EscalationDecider — when to wake you
  preview.py     loop   dry-run that ties them together into a decision log
"""
from sentigent.operator.risk import RiskAssessor, RiskScore
from sentigent.operator.plan import Plan, Step, parse_plan
from sentigent.operator.gate import ProfileGate, Verdict
from sentigent.operator.escalation import EscalationDecider, EscalationDecision
from sentigent.operator.runner import OperatorRunner, TurnResult, parse_stream_json
from sentigent.operator.operate import operate, RunResult, StepOutcome

__all__ = [
    "RiskAssessor",
    "RiskScore",
    "Plan",
    "Step",
    "parse_plan",
    "ProfileGate",
    "Verdict",
    "EscalationDecider",
    "EscalationDecision",
    "OperatorRunner",
    "TurnResult",
    "parse_stream_json",
    "operate",
    "RunResult",
    "StepOutcome",
]
