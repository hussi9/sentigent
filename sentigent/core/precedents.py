"""Decision precedent gate — real human decisions outrank statistical signals.

The 2026-07-07 principal review found the signal gate almost always returns
PROCEED on live tool calls (contexts carry no numeric baselines), while the
genuinely honest signal — ``decision_events`` rows recording moments the human
approved, rejected, corrected, or reverted work — never influenced verdicts.
This module closes that loop: before the signal if-ladder runs, evaluate()
asks whether enough consistent human precedent exists for this kind of action
and, if so, uses it.

Distinct from ``sentigent.operator`` precedents, which are answered-escalation
Q&A pairs for the autonomous loop's blocker resolver. This gate is about
tool-call verdicts inside the judgment engine.

Deterministic, no ML, no LLM. PolicyWall / org policies stay strictly above
this gate — precedents can only act in non-policy space.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

# How human event kinds map onto engine actions. reject/revert are the
# strongest signals ("I did not want that") → escalate to the human before
# repeating it. correct means "close, but I had to fix it" → slow down.
KIND_TO_ACTION: dict[str, str] = {
    "reject": "escalate",
    "revert": "escalate",
    "correct": "slow_down",
    "approve": "proceed",
}

MIN_PRECEDENTS = 3
MIN_AGREEMENT = 0.8
_CACHE_TTL_S = 60.0

# Destructive/forceful flags that must survive signature normalization —
# `git push` and `git push --force` are different actions to a human.
_SIGNIFICANT_FLAGS = re.compile(
    r"--force(?:-with-lease)?|--hard|--no-verify|-rf\b|-fr\b|(?<=\s)-f\b|--delete|--prune"
)

# Sensitive file buckets: these basenames matter more than their suffix.
_SENSITIVE_FILE = re.compile(r"(\.env[\w.]*|credentials?[\w.]*|[\w.-]*\.pem|id_rsa[\w.]*)$", re.IGNORECASE)


def normalize_signature(tool_name: str, tool_input: str) -> str:
    """Collapse a tool call into a stable, comparable signature.

    Bash → first two command words plus any destructive flags, lowercased
    ("bash:git push --force"). Compound commands are truncated at the first
    connector so the leading action names the signature.
    Edit/Write/Read → sensitive-basename bucket when matched, else the file
    suffix ("edit:.env", "write:.yaml").
    """
    tool = (tool_name or "").strip().lower()
    text = (tool_input or "").strip()

    if tool == "bash":
        # Truncate at command connectors; the leading command is the action.
        head = re.split(r"&&|\|\||;|\|", text, maxsplit=1)[0].strip()
        words = head.split()
        base = " ".join(w.lower() for w in words[:2])
        # Append significant flags not already captured by the first two words
        # (e.g. `git push --force` → keep --force; `rm -rf` already has it).
        flags = [
            f.strip() for f in sorted(set(_SIGNIFICANT_FLAGS.findall(head)))
            if f.strip() not in base
        ]
        if flags:
            base += " " + " ".join(flags)
        return f"bash:{base}"

    # File-shaped tools: bucket by sensitive basename, else by suffix.
    path = text.split()[0] if text else ""
    m = _SENSITIVE_FILE.search(path)
    if m:
        name = m.group(1).lower()
        if name.startswith(".env"):
            bucket = ".env"
        elif name.startswith("credential"):
            bucket = "credentials"
        elif name.endswith(".pem"):
            bucket = ".pem"
        else:
            bucket = "id_rsa"
        return f"{tool}:{bucket}"
    suffix = ""
    basename = path.rsplit("/", 1)[-1]
    if "." in basename:
        suffix = "." + basename.rsplit(".", 1)[-1].lower()
    return f"{tool}:{suffix}"


@dataclass
class PrecedentVerdict:
    """Outcome of a precedent lookup with enough consistent human signal."""

    action: str
    sample_size: int
    agreement: float
    reason: str


class PrecedentGate:
    """Looks up human decision_events matching an action signature.

    The full event set is small (hundreds of rows), so it is loaded once and
    cached with a short TTL; lookup is a dict access. Fails open: any storage
    error yields None and the signal gate proceeds as before.
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._cache: dict[str, list[str]] | None = None
        self._cache_at = 0.0

    def _events_by_signature(self) -> dict[str, list[str]]:
        now = time.monotonic()
        if self._cache is not None and now - self._cache_at < _CACHE_TTL_S:
            return self._cache
        grouped: dict[str, list[str]] = {}
        try:
            events = self._store.get_decision_events(limit=5000)
        except Exception:
            events = []

        # A decision_event records the human REACTING to a prior action; its
        # prior_trace_id links to the episode of the action that was judged.
        # We key precedents on THAT original action's signature — not on the
        # reaction's own text — so that when the agent is about to take a
        # similar action again, the precedent fires. (Keying on a revert
        # command's own text would instead escalate the human's corrective
        # action, the opposite of the intent.)
        actionable = [
            ev for ev in events
            if KIND_TO_ACTION.get((ev.get("kind") or "").lower()) is not None
            and (ev.get("prior_trace_id") or "").strip()
        ]
        prior_ids = [ev["prior_trace_id"].strip() for ev in actionable]
        try:
            episodes = self._store.get_episodes_by_trace_ids(prior_ids)
        except Exception:
            episodes = {}

        for ev in actionable:
            action = KIND_TO_ACTION[(ev.get("kind") or "").lower()]
            ep = episodes.get(ev["prior_trace_id"].strip())
            if not ep:
                continue  # the judged episode isn't in the brain — can't key it
            ctx = ep.get("context") or {}
            tool = ctx.get("tool_name") or ""
            payload = str(ctx.get("tool_input") or ep.get("task") or "")
            if not tool and ":" in payload:
                # Legacy episodes stored task as "Tool: input"; recover the tool.
                head, _, rest = payload.partition(":")
                if head.strip().isalpha():
                    tool, payload = head.strip(), rest.strip()
            # When tool_input was absent we fell back to task, which for legacy
            # episodes is prefixed "Tool: " — strip it so the stored signature
            # matches what a live evaluate() lookup produces (else keys like
            # "bash:bash: cd" never fire).
            if tool and payload.lower().startswith(tool.lower() + ":"):
                payload = payload[len(tool) + 1:].strip()
            if not tool or not payload:
                continue
            grouped.setdefault(normalize_signature(tool, payload), []).append(action)

        self._cache = grouped
        self._cache_at = now
        return grouped

    def lookup(self, signature: str) -> PrecedentVerdict | None:
        """Return a verdict when >=MIN_PRECEDENTS events agree >=MIN_AGREEMENT."""
        actions = self._events_by_signature().get(signature)
        if not actions or len(actions) < MIN_PRECEDENTS:
            return None
        counts: dict[str, int] = {}
        for a in actions:
            counts[a] = counts.get(a, 0) + 1
        top_action, top_count = max(counts.items(), key=lambda kv: kv[1])
        agreement = top_count / len(actions)
        if agreement < MIN_AGREEMENT:
            return None
        return PrecedentVerdict(
            action=top_action,
            sample_size=len(actions),
            agreement=agreement,
            reason=(
                f"you have {top_count}/{len(actions)} recorded decisions "
                f"treating '{signature}' this way"
            ),
        )
