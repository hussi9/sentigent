"""Backfill precedents from already-answered escalations — close the learning loop.

The operator is supposed to compound: when you answer a blocker, that answer becomes a
*precedent* so the clone resolves that class of blocker itself next time. But if answers were
recorded before the write-back was wired — or by a stale server process — the precedents never
accrue, and the clone keeps resolving ungrounded. (This is exactly what a 2026-06-12 code review
found: 11 real answers, 0 precedents. See `docs/DECISIONS.md` D-010.)

`backfill_precedents` walks every answered escalation and ensures each is represented as a
precedent, using the store's own learn write-back. It is **idempotent**: an escalation already
turned into a precedent is skipped, so it's safe to run repeatedly.

Idempotency keys on `(blocker, decision)`, NOT blocker text alone. The same blocker answered two
different ways — "build demo?" → approve once, skip another time — is two *distinct* precedents,
not a duplicate. Keying on blocker alone silently dropped the second answer (a 2026-06-12 code
review found this; see D-014). We normalize the decision the same way the store does so the key
matches the precedent the write-back actually records.

Pure read-over-store + the store's existing `learn_from_escalation_answer`. Never raises on a
single bad row — it counts the failure and moves on.
"""
from __future__ import annotations

from typing import Any


def _norm_decision(decision: str) -> str:
    """Mirror MemoryStore.learn_from_escalation_answer's decision mapping EXACTLY so the dedup
    key matches the `decision` a precedent is actually stored with. Keep this in lockstep with
    the store's vocabulary map (store.py learn_from_escalation_answer) — extra synonyms here would
    make the key diverge from the stored precedent and re-create duplicates on re-run."""
    d = (decision or "").strip().lower()
    if d in ("approve", "yes", "ok", "go", "proceed", "y", "continue"):
        return "approve"
    if d in ("skip", "next", "ignore", "drop"):
        return "skip"
    if d in ("takeover", "take over", "handover", "stop"):
        return "takeover"
    return d


def backfill_precedents(store: Any, dry_run: bool = False) -> dict:
    """Ensure every answered escalation has a precedent. Returns a summary dict.

    dry_run=True reports what *would* be created without writing. Idempotent either way."""
    try:
        answered = store.get_escalations(status="answered", limit=10_000) or []
    except Exception:
        answered = []
    try:
        # A precedent is keyed by (blocker, decision): blocker is the escalation question, decision
        # is the normalized answer (see learn_from_escalation_answer). Same blocker + same decision
        # is a real duplicate; same blocker + different decision is a distinct precedent.
        seen = {(str(p.get("blocker", "")), str(p.get("decision", "")))
                for p in (store.get_precedents() or [])}
    except Exception:
        seen = set()

    created = skipped_dup = skipped_no_decision = errors = 0
    created_ids: list = []

    for esc in answered:
        question = str(esc.get("question", ""))
        decision = str(esc.get("user_decision", "")).strip()
        if not decision:
            skipped_no_decision += 1
            continue
        key = (question, _norm_decision(decision))
        if key in seen:
            skipped_dup += 1
            continue
        if dry_run:
            created += 1
            seen.add(key)  # don't double-count within one dry run
            continue
        try:
            res = store.learn_from_escalation_answer(int(esc.get("id", 0)), decision)
            if isinstance(res, dict) and res.get("learned"):
                created += 1
                seen.add(key)
                pid = res.get("precedent_id")
                if pid:
                    created_ids.append(pid)
            else:
                errors += 1
        except Exception:
            errors += 1

    return {
        "answered": len(answered),
        "created": created,
        "skipped_already_learned": skipped_dup,
        "skipped_no_decision": skipped_no_decision,
        "errors": errors,
        "created_precedent_ids": created_ids,
        "dry_run": dry_run,
    }
