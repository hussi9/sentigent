"""RiskAssessor + PolicyWall — the hard, profile-independent risk floor (D3/F3).

This is deterministic regex, NOT learned judgment. It exists because some actions
are dangerous regardless of how confident the profile is: force-pushing main,
touching prod DB unattended, deleting outside a worktree, committing secrets,
sending external email. PolicyWall rules OVERRIDE the profile — they can force an
escalation even when the gate says "proceed."

Promoted from the one thing that actually worked in old sentigent (policies.py
regexes), reframed from "advisory judgment" to "inviolable guardrail."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RiskScore:
    score: float          # 0.0 (trivial) .. 1.0 (maximum blast radius)
    category: str         # deploy | prod_db | force_push | delete | secrets | external_send | install | normal
    reasons: list[str] = field(default_factory=list)
    policy_wall: bool = False  # True => a hard never-do-unattended rule fired

    @property
    def level(self) -> str:
        if self.policy_wall or self.score >= 0.8:
            return "critical"
        if self.score >= 0.5:
            return "high"
        if self.score >= 0.25:
            return "medium"
        return "low"


# (compiled pattern, category, base risk, is_policy_wall, human reason)
_RULES: list[tuple[re.Pattern, str, float, bool, str]] = [
    (re.compile(r"git\s+push\s+.*(--force|-f)\b.*\b(main|master|origin)\b", re.I),
     "force_push", 0.95, True, "force-push to a shared branch"),
    (re.compile(r"\bgit\s+push\s+.*(--force|-f)\b", re.I),
     "force_push", 0.85, True, "force-push"),
    (re.compile(r"\b(supabase\s+db\s+push|drop\s+table|truncate\s+table|delete\s+from)\b", re.I),
     "prod_db", 0.9, True, "destructive/prod database operation"),
    (re.compile(r"\balter\s+table\b|\bmigrat", re.I),
     "prod_db", 0.65, False, "database schema change"),
    (re.compile(r"\brm\s+-rf\b|\bunlink\b|\brmdir\b", re.I),
     "delete", 0.8, True, "recursive delete"),
    (re.compile(r"\b(api[_-]?key|secret|token|password|private[_-]?key|service[_-]?role)\b", re.I),
     "secrets", 0.75, True, "touches credentials/secrets"),
    (re.compile(r"\b(resend|sendgrid|smtp|gmail\.send|mailgun|postmark|tweet)\b"
                r"|\bsend(s|ing)?\b.{0,30}\b(email|message|announcement|invite|dm)\b"
                r"|\b(email|announcement)\b.{0,30}\b(list|beta|customers?|users?|subscribers?|everyone)\b"
                r"|\b(slack|discord)\b.{0,20}\b(post|message|send)\b"
                r"|\bpublish\b.{0,20}\b(post|tweet|announcement)\b", re.I),
     "external_send", 0.7, True, "sends something external (email/social)"),
    (re.compile(r"\b(vercel\s+(--prod|deploy)|eas\s+build|eas\s+submit|cloud\s*run\s+deploy|fly\s+deploy|netlify\s+deploy)\b", re.I),
     "deploy", 0.7, False, "production deploy"),
    (re.compile(r"\b(npm|pnpm|yarn|pip|brew)\s+(install|add|i)\b", re.I),
     "install", 0.3, False, "installs a dependency"),
]


class RiskAssessor:
    """Classify a step/action's blast radius. Pure, fast, deterministic."""

    def assess(self, text: str) -> RiskScore:
        if not text:
            return RiskScore(0.0, "normal", [])
        best: RiskScore | None = None
        wall_fired = False
        wall_reasons: list[str] = []
        for pat, category, base, wall, reason in _RULES:
            if pat.search(text):
                if wall:
                    wall_fired = True
                    if reason not in wall_reasons:
                        wall_reasons.append(reason)
                if best is None or base > best.score:
                    best = RiskScore(base, category, [reason], wall)
        if best is None:
            return RiskScore(0.05, "normal", ["routine change"])
        # PolicyWall is STICKY: if ANY hard-rule matched, the verdict must carry policy_wall=True
        # regardless of which rule won the score. The old code carried the wall flag on whichever
        # rule had the highest base — safe only by the numeric coincidence that no non-wall base
        # exceeded any wall base. One future rule edit (e.g. a 0.9 non-wall "deploy-to-prod" rule)
        # would have silently dropped a co-occurring hard-rule escalation. Fail closed instead.
        if wall_fired and not best.policy_wall:
            best.policy_wall = True
            for r in wall_reasons:
                if r not in best.reasons:
                    best.reasons.append(r)
        return best
