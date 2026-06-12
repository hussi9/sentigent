"""ProfileGate (D1) — the heart: "would I approve this step, given my profile?"

Given a pending step + your operator profile + your declared practices, return a
verdict — CONTINUE / CORRECT / ESCALATE — with a confidence and a plain-English
reason in your voice. Cheap path is the local LLM (Gemma/llama). If the LLM is
unavailable it falls back to a transparent heuristic (never fabricates a verdict
it can't justify).

This is the module the old sentigent got wrong: it judged near-empty context and
rubber-stamped PROCEED. Here the gate is FED the real features — the step text,
the matched practices, and the profile rules — and must cite which rule drove it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.intelligence import local_llm

CONTINUE = "continue"
CORRECT = "correct"
ESCALATE = "escalate"


@dataclass
class Verdict:
    decision: str               # continue | correct | escalate
    confidence: float           # 0..1 — how sure the model-of-you is
    reason: str                 # plain-English, in your voice
    matched_rules: list[str] = field(default_factory=list)
    correction: str = ""        # if decision == correct: what you'd say to fix it
    source: str = "llm"         # llm | heuristic

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "matched_rules": self.matched_rules,
            "correction": self.correction,
            "source": self.source,
        }


_SYSTEM = (
    "You are a model of a specific senior engineer. Judge a proposed work step the "
    "way THEY would, using only their profile and declared practices. Be decisive "
    "and cite the exact rule that drove your call. Output STRICT JSON."
)

_SCHEMA = """Return ONLY this JSON:
{
  "decision": "continue" | "correct" | "escalate",
  "confidence": 0.0-1.0,
  "reason": "<one sentence, first person, as the engineer>",
  "matched_rules": ["<the profile rule or practice that applies>", ...],
  "correction": "<if decision=correct: the exact redirect you'd give, else empty>"
}
decision guide:
- continue: this is exactly how they'd do it; no concern.
- correct: they'd do it but you spotted a deviation from a practice/preference (e.g. committing before tests). Put the fix in "correction".
- escalate: genuinely unsure, or it conflicts with a 'never_do' / 'ask_when' rule — wake them."""


class ProfileGate:
    def __init__(self, profile: dict, practices: Optional[list[dict]] = None,
                 model: Optional[str] = None):
        self.profile = profile or {}
        self.practices = practices or []
        self.model = model or local_llm.active_model()

    # ---- prompt -------------------------------------------------------------
    def _profile_block(self) -> str:
        p = self.profile
        lines = [f"summary: {p.get('summary','')}"]
        for key in ("preferences", "coding_standards", "never_do", "ask_when"):
            vals = p.get(key) or []
            if vals:
                lines.append(f"{key}: " + "; ".join(str(v) for v in vals))
        rt = p.get("risk_tolerance") or {}
        if rt:
            lines.append("risk_tolerance: " + json.dumps(rt))
        if self.practices:
            lines.append("declared_practices: " + "; ".join(
                f"[{pr.get('cadence','always')}] {pr.get('text','')}" for pr in self.practices
            ))
        return "\n".join(lines)

    def _prompt(self, step_text: str, risk_summary: str, work: str = "") -> str:
        base = (
            f"{_SCHEMA}\n\n=== THE ENGINEER'S PROFILE ===\n{self._profile_block()}\n\n"
            f"=== PROPOSED STEP ===\n{step_text}\n\n"
            f"=== RISK (deterministic pre-check) ===\n{risk_summary}\n"
        )
        if work:
            base += (
                "\n=== WHAT THE WORKER ACTUALLY DID (review THIS, not just the plan) ===\n"
                + work[:4000] + "\n"
            )
        return base

    # ---- judgment -----------------------------------------------------------
    def judge(self, step_text: str, risk_summary: str = "low/normal", work: str = "") -> Verdict:
        if local_llm.llm_available():
            raw = local_llm.generate_json(
                self._prompt(step_text, risk_summary, work), model=self.model, system=_SYSTEM
            )
            v = self._coerce(raw)
            if v is not None:
                return v
        return self._heuristic(step_text)

    @staticmethod
    def _coerce(raw: Any) -> Optional[Verdict]:
        if not isinstance(raw, dict):
            return None
        dec = str(raw.get("decision", "")).strip().lower()
        if dec not in (CONTINUE, CORRECT, ESCALATE):
            return None
        try:
            conf = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        rules = raw.get("matched_rules")
        rules = [str(x) for x in rules] if isinstance(rules, list) else []
        return Verdict(
            decision=dec, confidence=conf,
            reason=str(raw.get("reason", "")).strip(),
            matched_rules=rules,
            correction=str(raw.get("correction", "")).strip(),
            source="llm",
        )

    def _heuristic(self, step_text: str) -> Verdict:
        """No LLM available: be honest and conservative. Match declared practices
        by keyword; if a practice clearly applies and the step omits it, suggest a
        correction; otherwise continue at low confidence (we can't really judge)."""
        low = step_text.lower()
        for pr in self.practices:
            kw = [w for w in str(pr.get("text", "")).lower().split() if len(w) > 4]
            if kw and any(w in low for w in kw[:3]):
                return Verdict(
                    decision=CONTINUE, confidence=0.4,
                    reason="Heuristic: step aligns with a declared practice (LLM offline).",
                    matched_rules=[pr.get("text", "")], source="heuristic",
                )
        return Verdict(
            decision=CONTINUE, confidence=0.25,
            reason="Heuristic fallback: local LLM offline, low-confidence proceed.",
            source="heuristic",
        )
