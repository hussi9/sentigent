"""Operator dry-run preview — the brain made visible.

Given a plan + your stored profile + declared practices, walk every pending step
and show what the Operator WOULD do as you: proceed silently, auto-correct, or
wake you — with the risk floor and the reasoning. Nothing executes. This is the
"watch it think as me" view that earns trust before any real autonomy (Phase 1).

Returns a structured result the CLI renders, plus the headline metric the design
cares about: how far it gets between the steps where it'd stop to ask you.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.core import clone_readiness
from sentigent.operator.escalation import EscalationDecider, EscalationDecision, ASSISTED
from sentigent.operator.gate import ProfileGate, Verdict
from sentigent.operator.plan import Plan, Step
from sentigent.operator.risk import RiskAssessor, RiskScore


@dataclass
class StepReview:
    step: Step
    risk: RiskScore
    verdict: Verdict
    escalation: EscalationDecision

    def to_dict(self) -> dict:
        return {
            "idx": self.step.idx,
            "description": self.step.description,
            "domain": self.step.domain,
            "risk": {"score": round(self.risk.score, 2), "category": self.risk.category,
                     "level": self.risk.level, "policy_wall": self.risk.policy_wall},
            "verdict": self.verdict.to_dict(),
            "escalation": self.escalation.to_dict(),
        }


@dataclass
class PreviewResult:
    goal: str
    autonomy: str
    readiness: dict
    reviews: list[StepReview] = field(default_factory=list)
    profile_source: str = "none"

    @property
    def asks(self) -> int:
        return sum(1 for r in self.reviews if r.escalation.ask)

    @property
    def auto(self) -> int:
        return sum(1 for r in self.reviews if not r.escalation.ask)

    @property
    def longest_unattended_run(self) -> int:
        """Max consecutive auto-proceed steps — the headline 'distance between
        escalations' metric. Higher = the clone needs you less."""
        best = run = 0
        for r in self.reviews:
            if r.escalation.ask:
                run = 0
            else:
                run += 1
                best = max(best, run)
        return best

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "autonomy": self.autonomy,
            "profile_source": self.profile_source,
            "readiness": self.readiness,
            "summary": {
                "steps": len(self.reviews),
                "auto_proceed": self.auto,
                "would_ask": self.asks,
                "longest_unattended_run": self.longest_unattended_run,
            },
            "reviews": [r.to_dict() for r in self.reviews],
        }


def preview_plan(
    store: Any, plan: Plan, autonomy: str = ASSISTED,
    model: Optional[str] = None,
) -> PreviewResult:
    """Run the dry-run judgment over a plan's pending steps."""
    # Load the model-of-you.
    profile: dict = {}
    source = "none"
    try:
        latest = store.get_latest_operator_profile()
        if latest:
            profile = json.loads(latest.get("profile_json", "{}"))
            source = latest.get("source", "none")
    except Exception:
        pass
    try:
        practices = store.get_practices(active_only=True)
    except Exception:
        practices = []

    readiness = clone_readiness.compute(store).to_dict()
    assessor = RiskAssessor()
    gate = ProfileGate(profile, practices, model=model)
    decider = EscalationDecider(autonomy)

    reviews: list[StepReview] = []
    for step in plan.pending:
        risk = assessor.assess(step.description)
        verdict = gate.judge(step.description, risk_summary=f"{risk.level}/{risk.category}")
        esc = decider.decide(step.description, verdict, risk)
        reviews.append(StepReview(step, risk, verdict, esc))

    return PreviewResult(
        goal=plan.goal, autonomy=autonomy, readiness=readiness,
        reviews=reviews, profile_source=source,
    )
