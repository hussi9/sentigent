"""DecisionCapture — record the REAL user-preference signal (Phase 0, A1).

The old system labelled "a tool ran without error" as `correct`, which says
nothing about whether the *decision* was good. The honest signal is what the
human actually does in reaction to the agent's work:

  - approve   — "perfect", "lgtm", "ship it", "yes that works"
  - reject    — "no", "stop", "don't", "that's wrong", "undo"
  - correct   — "actually ...", "instead ...", "should be ...", "do it this way"
  - revert    — git revert / reset --hard / checkout -- / restore (an unambiguous
                "that prior work was wrong" signal)

These become rows in `decision_events`, the fuel for the operator profile. The
classifiers here are deliberately conservative: when in doubt, return None
(neutral) rather than inventing a signal. Garbage-in was the original disease.

See docs/plans/2026-06-03-operator-autopilot-design.md (A1 / DecisionCapture).
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

# ---- prompt-reaction classification ----------------------------------------
# Patterns are matched against the user's prompt. Ordered by precedence:
# reject/correct (negative, high-value) win over approve when both appear.

_REJECT_RE = re.compile(
    r"\b(undo|revert that|roll ?back|that'?s wrong|that is wrong|not what i|"
    r"don'?t do that|stop|abort|cancel that|nope|that'?s not right|"
    r"you broke|this is broken|that broke)\b",
    re.IGNORECASE,
)
_CORRECT_RE = re.compile(
    r"\b(actually|instead|rather|should be|should have|do it this way|"
    r"the right way|use .* instead|change it to|not like that|redo)\b",
    re.IGNORECASE,
)
_APPROVE_RE = re.compile(
    r"\b(perfect|lgtm|looks good|great work|nice work|that works|ship it|"
    r"exactly right|love it|that'?s correct|works great|approved)\b",
    re.IGNORECASE,
)

# Escape / meta markers that are NOT reactions to the agent's work.
_NOT_A_REACTION_RE = re.compile(
    r"^\s*(\[no-router\]|\[skip-router\]|/[\w:-]+)\b", re.IGNORECASE
)


def classify_prompt_reaction(prompt: str) -> Optional[str]:
    """Classify a user prompt as a reaction to the agent's prior work.

    Returns 'reject' | 'correct' | 'approve', or None when the prompt carries no
    clear preference signal (the common case — most prompts are new requests).
    Conservative by design: negative signals win, ambiguity returns None.
    """
    if not prompt or _NOT_A_REACTION_RE.match(prompt):
        return None
    if _REJECT_RE.search(prompt):
        return "reject"
    if _CORRECT_RE.search(prompt):
        return "correct"
    if _APPROVE_RE.search(prompt):
        return "approve"
    return None


# ---- git-revert detection ---------------------------------------------------

_REVERT_RE = re.compile(
    r"\bgit\s+(revert|reset\s+--hard|checkout\s+--|restore(\s|$)|"
    r"reset\s+HEAD~|clean\s+-[a-z]*f)",
    re.IGNORECASE,
)


def detect_revert_from_bash(command: str) -> bool:
    """True if a Bash command undoes prior committed/working-tree work.

    A revert is a strong negative signal: whatever was just done is being thrown
    away. Matches git revert / reset --hard / checkout -- / restore / clean -f.
    """
    if not command:
        return False
    return bool(_REVERT_RE.search(command))


# ---- the writer -------------------------------------------------------------


def build_decision_event(
    kind: str,
    *,
    agent_id: str,
    org_id: str = "default",
    signal: str = "",
    target: str = "",
    prior_trace_id: str = "",
    source: str = "",
    confidence: float = 1.0,
    domain: str = "global",
    ts: Optional[float] = None,
    meta: str = "{}",
) -> dict[str, Any]:
    """Construct a decision_events row dict (matches store.insert_decision_event)."""
    return {
        "agent_id": agent_id,
        "org_id": org_id,
        "ts": ts if ts is not None else time.time(),
        "kind": kind,
        "domain": domain,
        "signal": signal,
        "target": target,
        "prior_trace_id": prior_trace_id,
        "source": source,
        "confidence": confidence,
        "meta": meta,
    }


class DecisionCapture:
    """Thin orchestrator: classify a signal and persist it via the store.

    Fail-soft everywhere — capturing a preference signal must never break the
    user's session. `store` only needs `.insert_decision_event(dict)`.
    """

    def __init__(self, store: Any, agent_id: str, org_id: str = "default") -> None:
        self.store = store
        self.agent_id = agent_id
        self.org_id = org_id

    def _write(self, kind: str, **kw: Any) -> Optional[dict[str, Any]]:
        try:
            event = build_decision_event(
                kind, agent_id=self.agent_id, org_id=self.org_id, **kw
            )
            self.store.insert_decision_event(event)
            return event
        except Exception:
            return None

    def capture_prompt_reaction(
        self, prompt: str, prior_trace_id: str = ""
    ) -> Optional[dict[str, Any]]:
        """Classify a user prompt; write a decision_event if it's a real reaction."""
        kind = classify_prompt_reaction(prompt)
        if kind is None:
            return None
        return self._write(
            kind,
            signal=(prompt or "")[:500],
            prior_trace_id=prior_trace_id,
            source="prompt_reaction",
            confidence=0.7,  # text sentiment — strong but not certain
        )

    def capture_bash_revert(
        self, command: str, prior_trace_id: str = ""
    ) -> Optional[dict[str, Any]]:
        """Write a 'revert' decision_event if the command undoes prior work."""
        if not detect_revert_from_bash(command):
            return None
        return self._write(
            "revert",
            signal=(command or "")[:500],
            target=(command or "")[:200],
            prior_trace_id=prior_trace_id,
            source="bash_revert",
            confidence=0.9,  # an explicit revert is a near-unambiguous signal
        )
