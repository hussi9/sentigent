"""Practice enforcement gate — hold the agent to the practices you declared.

The 2026-07-07 review found the ``practices`` playbook (Layer A: "run tests
before committing", "gate merges on green CI") was *declared, counted, and
benchmarked* but never **enforced** — nothing stopped a commit that skipped the
practice. This gate closes that: at the moment a practice's cadence fires (e.g.
``git commit`` for a ``commit``-cadence practice), it checks whether the practice
was actually satisfied this session, and if not, acts per the user's chosen
enforcement level.

The user owns the dial (store.set_practice_enforcement):
  • off   → not gated
  • warn  → slow_down the action with a note (default)
  • block → escalate (hard-gate) until the practice is satisfied

So you stop having to prompt "did you run the tests?" — the gate remembers the
practice and enforces it for you.

Deterministic, no LLM. Sits below PolicyWall/graph/precedent (those are
inviolable / already-decided). Only POSITIVE "do-X-before-Y" practices are
enforced here; prohibitions ("never force-push") remain PolicyWall's job.
Satisfaction is judged from recent session tool calls using the same keyword
sets the best-practices KB already ships — no new signal invented. Fails open.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sentigent.operator.best_practices import UNIVERSAL

# Index the KB by key; each Practice carries cadence + keywords already.
_KB = {p.key: p for p in UNIVERSAL}

# Only positive "do-X-before-Y" practices are gate-enforceable — their keyword
# appearing in a recent tool call means the action happened. Prohibitions like
# no-force-push are inverted (keyword present = the bad thing) and belong to
# PolicyWall, not here.
ENFORCEABLE_KEYS = frozenset({
    "tests-before-commit",
    "ci-gate",
    "self-review-diff",
    "peer-review-risky",
    "staging-before-prod",
})

# What tool call fires each cadence. Milestone/always ride the commit trigger.
_CADENCE_TO_TRIGGER = {
    "commit": "commit",
    "milestone": "commit",
    "always": "commit",
    "pr": "pr",
    "deploy": "deploy",
}

_COMMIT_RE = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
_PR_RE = re.compile(r"\bgit\s+push\b|\bgh\s+pr\s+create\b", re.IGNORECASE)
_DEPLOY_RE = re.compile(
    r"\b(vercel\s+deploy|vercel\s+--prod|eas\s+build|eas\s+submit|"
    r"supabase\s+functions\s+deploy|netlify\s+deploy)\b",
    re.IGNORECASE,
)


def detect_trigger(task: str) -> str | None:
    """Return the practice trigger this tool call fires: 'commit'|'pr'|'deploy'|None."""
    text = task or ""
    if _COMMIT_RE.search(text):
        return "commit"
    if _PR_RE.search(text):
        return "pr"
    if _DEPLOY_RE.search(text):
        return "deploy"
    return None


def window_since_last_commit(recent_texts: list[str]) -> list[str]:
    """Trim recent tool calls to only those AFTER the previous commit.

    ``recent_texts`` is most-recent-first. The real question a commit-cadence
    practice asks is "did you do X since your *last* commit?" — work from before
    that commit belongs to an already-shipped cycle and must not satisfy this
    one. Cut the list at the first prior commit (exclusive). If there is no prior
    commit, the whole session window counts.
    """
    out: list[str] = []
    for t in recent_texts:
        if detect_trigger(t) == "commit":
            break
        out.append(t)
    return out


@dataclass
class PracticeVerdict:
    """A practice that fired at its cadence and was not satisfied."""

    action: str          # "escalate" (block) | "slow_down" (warn)
    practice_id: int
    practice_text: str
    kb_key: str
    enforcement: str
    reason: str


def _match_kb(text: str):
    """Map a declared practice sentence to its enforceable KB practice, if any."""
    for key in ENFORCEABLE_KEYS:
        kb = _KB.get(key)
        if kb is not None and kb.covered_by(text):
            return kb
    return None


class PracticeGate:
    """Enforces the user's active practices at their cadence.

    Reads practices from the store; judges satisfaction from recent session tool
    calls. Fails open — any error yields None and evaluate() proceeds.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def check(
        self,
        tool_name: str,
        task: str,
        recent_texts: list[str],
    ) -> PracticeVerdict | None:
        """Return a verdict when an active practice fires unsatisfied, else None.

        ``recent_texts`` are the task strings of recent session tool calls (the
        signal for "did the practice happen"). The first unsatisfied practice
        wins, block-level ahead of warn-level.
        """
        trigger = detect_trigger(task)
        if trigger is None:
            return None

        try:
            practices = self._store.get_practices(active_only=True)
        except Exception:
            return None

        lowered = [t.lower() for t in recent_texts if t]
        # For commit-cadence, only count work done since the previous commit —
        # "did you test since you last committed", not "ever this session".
        if trigger == "commit":
            lowered = window_since_last_commit(lowered)
        pending: list[PracticeVerdict] = []

        for pr in practices:
            enforcement = (pr.get("enforcement") or "warn").strip().lower()
            if enforcement == "off":
                continue
            kb = _match_kb(pr.get("text") or "")
            if kb is None or kb.key not in ENFORCEABLE_KEYS:
                continue
            if _CADENCE_TO_TRIGGER.get((pr.get("cadence") or "always").lower()) != trigger:
                continue

            satisfied = any(kb.covered_by(t) for t in lowered)
            pid = int(pr.get("id", 0))
            try:
                self._store.record_practice_adherence(pid, satisfied)
            except Exception:
                pass
            if satisfied:
                continue

            action = "escalate" if enforcement == "block" else "slow_down"
            verb = "requires" if enforcement == "block" else "expects"
            pending.append(PracticeVerdict(
                action=action,
                practice_id=pid,
                practice_text=pr.get("text") or "",
                kb_key=kb.key,
                enforcement=enforcement,
                reason=(
                    f"Practice '{pr.get('text')}' {verb} action before this "
                    f"{trigger}, and no matching step was detected this session"
                ),
            ))

        if not pending:
            return None
        # Block outranks warn — surface the hardest gate first.
        pending.sort(key=lambda v: 0 if v.enforcement == "block" else 1)
        return pending[0]
