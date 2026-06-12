"""ProfileBuilder — synthesize the operator profile (Phase 1, A2).

The first genuine *intelligence* task in sentigent: turn the explicit profile
(your CLAUDE.md / rules) plus the implicit signal (the honest decision_events
captured in Phase 0) into a structured "model of you" the autopilot can judge
against. Runs offline via the local LLM (Ollama, swappable to Gemma).

Fail-soft and non-fabricating: if the local LLM is unavailable, it returns an
`explicit_only` profile (the raw rules, no invented content) rather than guess.
See docs/plans/2026-06-03-operator-autopilot-design.md (A2 / ProfileBuilder).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from sentigent.intelligence import local_llm

# Keep the explicit-profile excerpt bounded so the prompt stays in-context on
# small local models. CLAUDE.md is large; the head carries the load-bearing rules.
_CLAUDE_MD_MAX_CHARS = 8000

_SYSTEM = (
    "You model a specific software engineer's working preferences so an AI agent "
    "can act AS them. Be concrete and faithful to the evidence. Never invent "
    "preferences that are not supported by the provided material. Output STRICT JSON."
)

_SCHEMA_HINT = """Return ONLY a JSON object with these keys:
{
  "summary": "<2-3 sentence description of how this engineer works>",
  "preferences": ["<concrete working preference>", ...],
  "coding_standards": ["<language/style/testing rule they follow>", ...],
  "never_do": ["<thing they never want done>", ...],
  "risk_tolerance": {"<domain e.g. deploy|db|frontend>": "low|medium|high", ...},
  "ask_when": ["<situation where the agent should stop and ask them>", ...]
}
Base every item on the EXPLICIT RULES and OBSERVED SIGNAL below. If signal is thin,
keep lists short and grounded — do not pad."""


class ProfileBuilder:
    def __init__(
        self,
        store: Any,
        agent_id: str,
        claude_md_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.store = store
        self.agent_id = agent_id
        self.model = model or local_llm.active_model()
        self.claude_md_path = claude_md_path or os.path.expanduser("~/.claude/CLAUDE.md")

    # ---- inputs --------------------------------------------------------------

    def _gather_explicit(self) -> str:
        """The hand-written profile: the user's CLAUDE.md (head, bounded)."""
        try:
            text = Path(self.claude_md_path).read_text(errors="replace")
        except OSError:
            return ""
        return text[:_CLAUDE_MD_MAX_CHARS]

    def _gather_implicit(self) -> str:
        """A compact summary of the captured preference signal (decision_events)."""
        try:
            counts = self.store.get_decision_event_counts()
        except Exception:
            counts = {}
        if not counts:
            return "No decision events captured yet (signal will accrue as the user works)."
        try:
            recent = self.store.get_decision_events(limit=20)
        except Exception:
            recent = []
        lines = [f"counts: {json.dumps(counts)}"]
        for ev in recent[:12]:
            kind = ev.get("kind", "")
            sig = (ev.get("signal", "") or "")[:120]
            lines.append(f"- {kind}: {sig}")
        return "\n".join(lines)

    # ---- synthesis -----------------------------------------------------------

    def _prompt(self, explicit: str, implicit: str) -> str:
        return (
            f"{_SCHEMA_HINT}\n\n"
            f"=== EXPLICIT RULES (the engineer's CLAUDE.md) ===\n{explicit}\n\n"
            f"=== OBSERVED SIGNAL (their approve/reject/correct/revert actions) ===\n{implicit}\n"
        )

    @staticmethod
    def _normalize(obj: dict) -> dict:
        """Coerce the LLM output into the canonical profile shape (defensive)."""
        def _list(v: Any) -> list:
            return [str(x) for x in v] if isinstance(v, list) else ([] if v is None else [str(v)])

        return {
            "summary": str(obj.get("summary", "")).strip(),
            "preferences": _list(obj.get("preferences")),
            "coding_standards": _list(obj.get("coding_standards")),
            "never_do": _list(obj.get("never_do")),
            "risk_tolerance": obj.get("risk_tolerance") if isinstance(obj.get("risk_tolerance"), dict) else {},
            "ask_when": _list(obj.get("ask_when")),
        }

    def build(self) -> dict:
        """Synthesize + persist a profile version. Always returns a profile dict
        with a `source` of 'llm' or 'explicit_only'. Never raises."""
        explicit = self._gather_explicit()
        implicit = self._gather_implicit()

        profile: Optional[dict] = None
        source = "explicit_only"
        if explicit and local_llm.llm_available():
            raw = local_llm.generate_json(
                self._prompt(explicit, implicit), model=self.model, system=_SYSTEM
            )
            if raw:
                profile = self._normalize(raw)
                source = "llm"

        if profile is None:
            # Honest fallback: no fabrication. Record that the LLM didn't run and
            # carry only what is literally true (we have the explicit rules on disk).
            profile = self._normalize({
                "summary": (
                    "Profile not synthesized — local LLM unavailable or no CLAUDE.md. "
                    "Explicit rules exist on disk but were not modeled."
                ),
            })

        payload = json.dumps({**profile, "source": source, "model": self.model})
        try:
            version = self.store.save_operator_profile(payload, source=source, model=self.model)
        except Exception:
            version = -1
        return {**profile, "source": source, "model": self.model, "version": version}
