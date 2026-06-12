"""Externalize the clone's judgment into a repo-legible document.

The harness-engineering insight (OpenAI, 2026): *what an agent can't see in-context
doesn't exist.* Sentigent's judgment lives in a private SQLite brain — invisible to
any other agent. This module renders that judgment as plain markdown (`JUDGMENT.md`)
so ANY agent reading the repo can act the way you would: your hard rules, your
learned precedents, and your calibrated confidence thresholds.

Pure read-over-store + render. Deterministic, no model.
"""
from __future__ import annotations

from typing import Any, Optional

# The inviolable rules the clone can never auto-clear (mirrors the operator's
# policy wall). Stated up front so any agent reads them first.
HARD_RULES = [
    "force-push to a shared branch",
    "destructive production-database ops (DROP/TRUNCATE/DELETE without a guard)",
    "`rm -rf` / irreversible file deletion",
    "writing or exposing secrets / credentials",
    "sending anything to an external party (email, post, deploy) unprompted",
]


def build_judgment_doc(store: Any, profile: Optional[dict] = None) -> str:
    """Render the clone's judgment as markdown. Never raises."""
    profile = profile or {}

    try:
        precedents = store.get_precedents() or []
    except Exception:
        precedents = []
    try:
        calibration = store.get_calibration() or {}
    except Exception:
        calibration = {}
    try:
        from sentigent.operator.resolver import CloneResolver
        thresholds = CloneResolver.thresholds_from_calibration(store) or {}
    except Exception:
        thresholds = {}

    out: list[str] = []
    out.append("# How I decide — my judgment, made legible")
    out.append("")
    out.append("> Auto-generated from the Sentigent brain by `scripts/export_judgment.py`.")
    out.append("> Any agent can read this to make calls the way I would, instead of guessing.")
    out.append("")

    out.append("## Hard rules — never auto-cleared")
    out.append("These always stop for a human, regardless of confidence:")
    for r in HARD_RULES:
        out.append(f"- {r}")
    out.append("")

    out.append("## Learned precedents — how I've answered past blockers")
    if precedents:
        out.append("| When blocked by | I decided | Because |")
        out.append("|---|---|---|")
        for p in precedents[:50]:
            blk = str(p.get("blocker", ""))[:80].replace("|", "/")
            dec = str(p.get("decision", "")).replace("|", "/")
            why = str(p.get("rationale", ""))[:90].replace("|", "/")
            out.append(f"| {blk} | **{dec}** | {why} |")
    else:
        out.append("_No precedents yet — they accrue every time I answer a blocker._")
    out.append("")

    out.append("## Calibrated confidence thresholds")
    out.append("How sure I must be to act autonomously in each category "
               "(learned from how often my past calls matched yours):")
    if thresholds:
        out.append("| Category | Threshold |")
        out.append("|---|---|")
        for cat, thr in sorted(thresholds.items()):
            out.append(f"| {cat} | {float(thr):.0%} |")
    else:
        out.append("_Using conservative defaults until more outcomes are recorded._")
    out.append("")

    practices = profile.get("practices") or profile.get("coding_standards") or []
    if practices:
        out.append("## Declared practices")
        for pr in practices:
            out.append(f"- {pr}")
        out.append("")

    if calibration:
        total = sum(int(v.get("total", 0)) for v in calibration.values())
        correct = sum(int(v.get("correct", 0)) for v in calibration.values())
        rate = (correct / total) if total else 0.0
        out.append(f"_Calibration to date: {correct}/{total} of my past calls matched "
                   f"yours ({rate:.0%}) across {len(calibration)} categories._")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
