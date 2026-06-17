"""CloneResolver — answer a blocker the way the user would, instead of halting.

This is the load-bearing organ of the Sentigent Loop. The ProfileGate (D1) only
*detects* uncertainty; the EscalationDecider (D4) then wakes the human. That wastes
the entire point of a model-of-you: at the moment a blocker appears, the clone
should answer "what would Hussain do here?" — and only page the real human when it
genuinely can't.

Flow: retrieve similar past decisions (precedents) → ask the local model (Gemma,
grounded in profile + precedents) for a decision in the user's voice with a
calibrated confidence → apply it iff confident AND not a hard rule, else escalate.

Local-only on purpose: privacy, cost, and the model-of-you lives on this machine.
Fail-soft: if the LLM is unavailable or emits garbage, return `needs_human` at
confidence 0 — never fabricate an auto-approval.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.intelligence import local_llm

# A big local resolver model (e.g. gemma3:27b) can take minutes to COLD-LOAD from
# disk on the first call. A timeout there must NOT be misread as "the clone is
# unsure" — so we give the resolver a generous, env-tunable budget. Once warm,
# calls return in seconds.
_RESOLVE_TIMEOUT = float(os.environ.get("SENTIGENT_RESOLVER_TIMEOUT", "300"))

# Resolution decisions.
APPROVE = "approve"        # do the step as proposed
SKIP = "skip"              # don't do this step; move on
NEEDS_HUMAN = "needs_human"  # genuinely unsure → wake the real user

_APPLYABLE = (APPROVE, SKIP)

# Per-category confidence floor: the resolver only auto-applies at/above this.
# Conservative by default; the calibration loop (Phase 5) tunes these from the
# override rate. Hard-floor categories are never auto-applied regardless (the
# policy_wall check in should_apply blocks them).
DEFAULT_THRESHOLD = 0.75
_CATEGORY_THRESHOLD = {
    "normal": 0.70,
    "low_confidence": 0.72,
    "gate_escalate": 0.78,
    "risk_ceiling": 0.85,
}


@dataclass
class Resolution:
    decision: str               # approve | skip | needs_human
    confidence: float           # 0..1 — how sure the clone is it speaks for you
    rationale: str              # plain-English, first person, in your voice
    drove: str = ""             # which precedent/rule id drove the call
    source: str = "llm"         # llm | fallback

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
            "drove": self.drove,
            "source": self.source,
        }


_SYSTEM = (
    "You ARE a specific senior engineer's clone. A piece of autonomous work just hit "
    "a blocker and the loop is about to wake the real engineer. Your job is to answer "
    "it AS THEM so they don't have to — but ONLY if you are genuinely confident you "
    "know what they'd say. Use their profile and the precedents (their past answers to "
    "similar blockers). If unsure, say needs_human. Output STRICT JSON."
)

_SCHEMA = """Return ONLY this JSON:
{
  "decision": "approve" | "skip" | "needs_human",
  "confidence": 0.0-1.0,
  "rationale": "<one sentence, first person, as the engineer>",
  "drove": "<the precedent or profile rule that decided it, else empty>"
}
decision guide:
- approve: you are confident they'd say 'yes, do it'.
- skip:    you are confident they'd say 'no, don't do this step, move on'.
- needs_human: you do NOT confidently know their call — wake them. Prefer this when unsure."""


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3}


class CloneResolver:
    """Resolve a blocker as the user. Reuses the profile + a precedent store."""

    def __init__(self, profile: dict, store: Optional[Any] = None,
                 model: Optional[str] = None):
        self.profile = profile or {}
        self.store = store
        self.model = model or local_llm.resolver_model()

    # ---- retrieval ----------------------------------------------------------
    def retrieve(self, blocker_text: str, category: str = "", k: int = 5) -> list[dict]:
        """Top-k precedents most similar to the blocker. Tries semantic (embedding
        cosine) ranking first — so 'can't push to prod' matches 'deploy blocked' even
        with zero shared words — and falls back to keyword overlap if embeddings are
        unavailable. Same-category precedents get a small boost. Fail-soft + testable."""
        if self.store is None:
            return []
        try:
            rows = self.store.get_precedents()
        except Exception:
            return []
        if not rows:
            return []
        sem = self._retrieve_semantic(rows, blocker_text, category, k)
        if sem is not None:
            return sem
        return self._retrieve_keyword(rows, blocker_text, category, k)

    def _retrieve_keyword(self, rows: list[dict], blocker_text: str,
                          category: str, k: int) -> list[dict]:
        bt = _tokens(blocker_text)
        scored: list[tuple[float, dict]] = []
        for r in rows:
            overlap = len(bt & _tokens(str(r.get("blocker", ""))))
            score = float(overlap)
            if category and str(r.get("category", "")) == category:
                score += 0.5
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]

    def _retrieve_semantic(self, rows: list[dict], blocker_text: str,
                           category: str, k: int) -> list[dict] | None:
        """Embedding-cosine ranking. Returns None (→ keyword fallback) if the
        embedder isn't available or anything goes wrong — never raises."""
        try:
            from sentigent.routing.embeddings import cosine_sim, encode
            q = encode(blocker_text)
            if not q:
                return None
            scored: list[tuple[float, dict]] = []
            for r in rows:
                emb = encode(str(r.get("blocker", "")))
                if not emb:
                    continue
                score = cosine_sim(q, emb)
                if category and str(r.get("category", "")) == category:
                    score += 0.05
                scored.append((score, r))
            if not scored:
                return None
            scored.sort(key=lambda x: x[0], reverse=True)
            return [r for _, r in scored[:k]]
        except Exception:
            return None

    # ---- prompt -------------------------------------------------------------
    def _profile_block(self) -> str:
        p = self.profile
        lines = [f"summary: {p.get('summary','')}"]
        for key in ("preferences", "coding_standards", "never_do", "ask_when"):
            vals = p.get(key) or []
            if vals:
                lines.append(f"{key}: " + "; ".join(str(v) for v in vals))
        return "\n".join(lines)

    @staticmethod
    def _precedent_block(precedents: list[dict]) -> str:
        if not precedents:
            return "(no similar past decisions on record)"
        out = []
        for i, r in enumerate(precedents, 1):
            out.append(
                f"[{i}] when blocked by: {str(r.get('blocker',''))[:120]}\n"
                f"    you decided: {r.get('decision','')} — {str(r.get('rationale',''))[:160]}"
            )
        return "\n".join(out)

    def _prompt(self, blocker: dict, precedents: list[dict]) -> str:
        return (
            f"{_SCHEMA}\n\n=== YOUR PROFILE ===\n{self._profile_block()}\n\n"
            f"=== YOUR PAST DECISIONS ON SIMILAR BLOCKERS ===\n"
            f"{self._precedent_block(precedents)}\n\n"
            f"=== THE BLOCKER NOW ===\n"
            f"step: {blocker.get('step_text','')}\n"
            f"why it blocked: {blocker.get('trigger','')} "
            f"({blocker.get('gate_reason','')})\n"
            f"risk: {blocker.get('risk_level','')}/{blocker.get('category','')}\n"
        )

    # ---- resolve ------------------------------------------------------------
    def resolve(self, blocker: dict, precedents: Optional[list[dict]] = None) -> Resolution:
        """Answer the blocker as the user. Never raises. Fail-soft → needs_human."""
        if precedents is None:
            precedents = self.retrieve(
                blocker.get("step_text", ""), blocker.get("category", "")
            )
        if not local_llm.llm_available():
            return Resolution(NEEDS_HUMAN, 0.0,
                              "Local model offline — can't speak for you, waking you.",
                              source="fallback")
        raw = local_llm.generate_json(
            self._prompt(blocker, precedents), model=self.model, system=_SYSTEM,
            timeout=_RESOLVE_TIMEOUT,
        )
        v = self._coerce(raw, precedents)
        if v is not None:
            return v
        return Resolution(NEEDS_HUMAN, 0.0,
                          "Couldn't get a clean read from the clone — waking you.",
                          source="fallback")

    @staticmethod
    def _coerce(raw: Any, precedents: list[dict]) -> Optional[Resolution]:
        if not isinstance(raw, dict):
            return None
        dec = str(raw.get("decision", "")).strip().lower()
        if dec not in (APPROVE, SKIP, NEEDS_HUMAN):
            return None
        try:
            conf = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        # needs_human means "I don't speak for you here" — confidence is meaningless.
        if dec == NEEDS_HUMAN:
            conf = 0.0
        return Resolution(
            decision=dec, confidence=conf,
            rationale=str(raw.get("rationale", "")).strip(),
            drove=str(raw.get("drove", "")).strip(),
            source="llm",
        )

    # ---- apply gate ---------------------------------------------------------
    @staticmethod
    def threshold_for(category: str, overrides: Optional[dict] = None) -> float:
        table = {**_CATEGORY_THRESHOLD, **(overrides or {})}
        return table.get(category or "normal", DEFAULT_THRESHOLD)

    @staticmethod
    def thresholds_from_calibration(store: Any, min_samples: int = 3,
                                    base: float = DEFAULT_THRESHOLD) -> dict:
        """Learn per-category thresholds from the override rate (Loop §4 / Phase 5).

        When the clone's past suggestions in a category matched the human's answer
        often (high calibration rate), trust it more → LOWER the bar. When they
        diverged, raise it → page the human more. Monotonic in the rate. Categories
        with too few samples keep their static default (returned absent here)."""
        try:
            cal = store.get_calibration()
        except Exception:
            return {}
        out: dict = {}
        for domain, stats in (cal or {}).items():
            total = int(stats.get("total", 0))
            if total < min_samples:
                continue
            rate = float(stats.get("rate", 0.0))
            # rate 1.0 → base-0.2 ; rate 0.0 → base+0.2 ; clamped to a sane band.
            thr = base + (0.5 - rate) * 0.4
            out[domain] = max(0.55, min(0.95, thr))
        return out

    @classmethod
    def should_apply(cls, resolution: Resolution, *, policy_wall: bool,
                     category: str = "normal",
                     thresholds: Optional[dict] = None) -> bool:
        """Apply the clone's answer autonomously iff it's an actionable decision,
        the clone is confident enough for this category, and it's NOT a hard rule.
        Hard-floor (policy_wall) is inviolable — the clone never auto-clears it."""
        if policy_wall:
            return False
        if resolution.decision not in _APPLYABLE:
            return False
        return resolution.confidence >= cls.threshold_for(category, thresholds)
