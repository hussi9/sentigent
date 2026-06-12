"""Brain health check — make silent loop failures loud (D-010).

A 2026-06-12 code review found the learning loop wasn't firing live: 11 answered escalations,
0 precedents — a stale MCP server recorded answers but skipped the learn write-back, and nothing
surfaced it. This reports the brain's vital signs and flags that exact symptom (and the related
"precedents but no calibration" one) so the failure is visible instead of invisible.

Pure read-over-store. Never raises.
"""
from __future__ import annotations

from typing import Any


def health_report(store: Any) -> dict:
    """Vital signs + warnings for the operator brain. ok=True when no warnings fire."""
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    answered = len(_safe(lambda: store.get_escalations(status="answered", limit=10_000), []))
    open_escs = len(_safe(lambda: store.get_escalations(status="open", limit=10_000), []))
    precedents = len(_safe(lambda: store.get_precedents(), []))
    cal = _safe(lambda: store.get_calibration(), {}) or {}
    cal_events = sum(int(v.get("total", 0)) for v in cal.values())

    warnings: list[str] = []
    # Symptom 1: answered escalations not represented as precedents → learn write-back not firing.
    # Measure it precisely with a dry-run backfill: it counts answered escalations whose
    # (blocker, decision) isn't already a precedent, using the SAME dedup the real backfill uses.
    # This catches PARTIAL staleness (some learned, some not) — which a bare precedents==0 misses —
    # and never false-alarms on legitimate dedup (D-016).
    unlearned = answered  # conservative fallback if the dry-run can't run
    try:
        from sentigent.operator.backfill import backfill_precedents
        unlearned = int(backfill_precedents(store, dry_run=True).get("created", 0))
    except Exception:
        pass
    learn_loop_ok = unlearned == 0
    if not learn_loop_ok:
        warnings.append(
            f"{unlearned} answered escalation(s) not yet learned as precedents — the learn "
            "write-back isn't firing (most often a stale MCP server). Run "
            "`python scripts/backfill_precedents.py` and reload the MCP server so future answers "
            "learn automatically."
        )
    # Symptom 2: precedents exist but calibration is empty → thresholds are static defaults.
    if precedents > 0 and cal_events == 0:
        warnings.append(
            "precedents exist but 0 calibration events — autonomy thresholds are running on "
            "static defaults. Calibration only accrues from resolver-attempted escalations "
            "(not hard-rule or verify-failed ones), so this is expected until such a blocker occurs."
        )

    return {
        "open_escalations": open_escs,
        "answered_escalations": answered,
        "precedents": precedents,
        "calibration_events": cal_events,
        "learn_loop_ok": learn_loop_ok,
        "warnings": warnings,
        "ok": len(warnings) == 0,
    }
