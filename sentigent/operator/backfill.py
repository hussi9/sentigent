"""Backfill precedents from already-answered escalations — close the learning loop.

The operator is supposed to compound: when you answer a blocker, that answer becomes a
*precedent* so the clone resolves that class of blocker itself next time. But if answers were
recorded before the write-back was wired — or by a stale server process — the precedents never
accrue, and the clone keeps resolving ungrounded. (This is exactly what a 2026-06-12 code review
found: 11 real answers, 0 precedents. See `docs/DECISIONS.md` D-010.)

`backfill_precedents` walks every answered escalation and ensures each is represented as a
precedent, using the store's own learn write-back. It is **idempotent**: an escalation already
turned into a precedent (matched by blocker text) is skipped, so it's safe to run repeatedly.

Pure read-over-store + the store's existing `learn_from_escalation_answer`. Never raises on a
single bad row — it counts the failure and moves on.
"""
from __future__ import annotations

from typing import Any


def backfill_precedents(store: Any, dry_run: bool = False) -> dict:
    """Ensure every answered escalation has a precedent. Returns a summary dict.

    dry_run=True reports what *would* be created without writing. Idempotent either way."""
    try:
        answered = store.get_escalations(status="answered", limit=10_000) or []
    except Exception:
        answered = []
    try:
        # A precedent's `blocker` is the escalation question (see learn_from_escalation_answer).
        seen = {str(p.get("blocker", "")) for p in (store.get_precedents() or [])}
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
        if question in seen:
            skipped_dup += 1
            continue
        if dry_run:
            created += 1
            seen.add(question)  # don't double-count within one dry run
            continue
        try:
            res = store.learn_from_escalation_answer(int(esc.get("id", 0)), decision)
            if isinstance(res, dict) and res.get("learned"):
                created += 1
                seen.add(question)
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
