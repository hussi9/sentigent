"""EscalationDecider (D4) — when to wake the human.

Combines the gate verdict (D1), its confidence, and the hard risk floor (D3/F3)
with the chosen autonomy level (H1) into a single call: proceed silently, or stop
and ask you. PolicyWall hard rules OVERRIDE everything — a force-push to main asks
you even at the highest autonomy.
"""
from __future__ import annotations

from dataclasses import dataclass

from sentigent.operator.gate import Verdict, ESCALATE, CORRECT, CONTINUE
from sentigent.operator.risk import RiskScore

# Autonomy ladder (H1). Higher = needs you less.
COPILOT = "copilot"      # approve every step
ASSISTED = "assisted"    # auto low-risk; ask on risky/novel
AUTOPILOT = "autopilot"  # unattended; ask only on real triggers
TRUSTED = "trusted"      # ask rarely; PolicyWall still inviolable

_LEVELS = (COPILOT, ASSISTED, AUTOPILOT, TRUSTED)

# Per-level: confidence below this on a CONTINUE => ask anyway.
_CONF_FLOOR = {COPILOT: 1.01, ASSISTED: 0.55, AUTOPILOT: 0.4, TRUSTED: 0.25}
# Per-level: risk at/above this => ask even on a confident continue.
_RISK_CEIL = {COPILOT: 0.0, ASSISTED: 0.5, AUTOPILOT: 0.7, TRUSTED: 0.85}


@dataclass
class EscalationDecision:
    ask: bool
    trigger: str          # why we're asking (or "auto-proceed")
    headline: str         # the one-line you'd see on your phone

    def to_dict(self) -> dict:
        return {"ask": self.ask, "trigger": self.trigger, "headline": self.headline}


class EscalationDecider:
    def __init__(self, autonomy: str = ASSISTED):
        self.autonomy = autonomy if autonomy in _LEVELS else ASSISTED

    def decide(self, step_text: str, verdict: Verdict, risk: RiskScore) -> EscalationDecision:
        a = self.autonomy

        # F3 PolicyWall — inviolable, overrides autonomy and the gate.
        if risk.policy_wall:
            return EscalationDecision(
                True, "policy_wall",
                f"HARD RULE: {step_text[:80]} — {', '.join(risk.reasons)}. Approve / Skip / Take over?",
            )

        # Gate says wake me.
        if verdict.decision == ESCALATE:
            return EscalationDecision(
                True, "gate_escalate",
                f"Unsure: {step_text[:80]} — {verdict.reason}",
            )

        # Copilot: you approve everything.
        if a == COPILOT:
            return EscalationDecision(True, "copilot", f"Approve step: {step_text[:80]}?")

        # Risk + confidence floors apply to ANY proceed-ish verdict (continue OR
        # correct). A high-risk deploy still asks even if the gate wanted to
        # auto-correct it — the correction doesn't lower the blast radius.
        if risk.score >= _RISK_CEIL[a]:
            return EscalationDecision(
                True, "risk_ceiling",
                f"Risky ({risk.category}): {step_text[:80]}. Approve / Skip / Take over?",
            )
        if verdict.confidence < _CONF_FLOOR[a]:
            return EscalationDecision(
                True, "low_confidence",
                f"Low confidence ({verdict.confidence:.0%}): {step_text[:80]} — {verdict.reason}",
            )

        # Below the floors: a correction is auto-applied (the operator redirects
        # itself); a clean continue just proceeds.
        if verdict.decision == CORRECT:
            return EscalationDecision(
                False, "auto-correct",
                f"Auto-correcting: {verdict.correction or verdict.reason}",
            )
        return EscalationDecision(False, "auto-proceed", f"Proceeding: {step_text[:80]}")
