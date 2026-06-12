"""Learned Steering File — emit an AGENTS.md from the clone brain.

Frontier teams (AWS / Kiro, 2026) lean on *steering files*: a repo-legible
document of conventions, coding standards, testing patterns, and the rules an
agent must follow. The catch is that teams hand-write them and they rot.

Sentigent already holds the same information as *behavior*: declared practices,
coding standards, hard rules, the precedents you've set answering blockers, and
the confidence thresholds calibrated from your outcomes. This module renders
that into the open `AGENTS.md` steering format any agent harness reads — learned
from how you actually work, not typed once and left to go stale. A drift line is
emitted when the brain has signal that a rule is being reverted.

Composes over `judgment_doc.py` (it reuses the same hard rules and precedent
reads). Pure read-over-store + render. Deterministic, no model. Never raises.
"""
from __future__ import annotations

from typing import Any, Optional

from sentigent.operator.judgment_doc import HARD_RULES


def _as_list(val: Any) -> list:
    if isinstance(val, list):
        return val
    if isinstance(val, (set, tuple)):
        return list(val)
    return []


def _practices(store: Any, profile: dict) -> list[dict]:
    """Declared practices as [{text, cadence}], from the store if available,
    else from the profile. Always returns a list of dicts; never raises."""
    rows: list = []
    try:
        rows = store.get_practices() or []  # type: ignore[attr-defined]
    except Exception:
        rows = []
    if not rows:
        rows = _as_list(profile.get("practices"))
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append({"text": str(r.get("text", "")), "cadence": str(r.get("cadence", "always"))})
        elif r:
            out.append({"text": str(r), "cadence": "always"})
    return [p for p in out if p["text"]]


def _drift_lines(store: Any) -> list[str]:
    """Rules showing churn — reverted/changed setup. Best-effort, lazy: emits
    nothing unless the brain actually has the signal. Never raises."""
    for getter in ("get_setup_changes", "get_recent_reverts"):
        try:
            rows = getattr(store, getter)() or []
        except Exception:
            rows = []
        if rows:
            lines = []
            for r in rows[:8]:
                if isinstance(r, dict):
                    what = str(r.get("what") or r.get("setting") or r.get("description", ""))[:90]
                    if what:
                        lines.append(what)
            if lines:
                return lines
    return []


def build_steering_doc(store: Any, profile: Optional[dict] = None,
                       project: Optional[str] = None) -> str:
    """Render the learned steering file (AGENTS.md) as markdown. Never raises."""
    profile = profile or {}
    name = project or "this repo"

    try:
        precedents = store.get_precedents() or []
    except Exception:
        precedents = []
    try:
        from sentigent.operator.resolver import CloneResolver
        thresholds = CloneResolver.thresholds_from_calibration(store) or {}
    except Exception:
        thresholds = {}

    coding = _as_list(profile.get("coding_standards"))
    prefs = _as_list(profile.get("preferences"))
    never = _as_list(profile.get("never_do"))
    ask_when = _as_list(profile.get("ask_when"))
    risk = profile.get("risk_tolerance") if isinstance(profile.get("risk_tolerance"), dict) else {}
    practices = _practices(store, profile)
    drift = _drift_lines(store)

    out: list[str] = []
    out.append("# AGENTS.md — how to work in this repo, as me")
    out.append("")
    out.append("> Auto-generated from the Sentigent brain by `scripts/export_steering.py`.")
    out.append("> This is a *learned* steering file: every rule below was modeled from how I "
               "actually work — declared practices, past decisions, and calibrated outcomes — "
               "not typed once and left to rot. Regenerate it any time; it tracks the truth.")
    if profile.get("summary"):
        out.append("")
        out.append(f"**Who you're standing in for:** {str(profile['summary'])[:400]}")
    out.append("")

    # 1. Hard rules — first, because they're inviolable.
    out.append("## Hard rules — never do these without asking")
    out.append("Stop and get a human regardless of confidence:")
    for r in HARD_RULES:
        out.append(f"- {r}")
    for r in never:
        out.append(f"- {r}")
    out.append("")

    # 2. Conventions & coding standards.
    if coding:
        out.append("## Conventions & coding standards")
        for c in coding:
            out.append(f"- {c}")
        out.append("")

    # 3. Practices — how work actually gets shipped (testing patterns live here).
    if practices:
        out.append("## How work gets done here")
        for p in practices:
            cad = p["cadence"]
            tag = f"_{cad}_ — " if cad and cad != "always" else ""
            out.append(f"- {tag}{p['text']}")
        out.append("")

    # 4. Preferences.
    if prefs:
        out.append("## Working preferences")
        for p in prefs:
            out.append(f"- {p}")
        out.append("")

    # 5. When to stop and ask.
    if ask_when:
        out.append("## When to stop and ask me")
        for a in ask_when:
            out.append(f"- {a}")
        out.append("")

    # 6. Risk posture by area.
    if risk:
        out.append("## Risk posture")
        out.append("How much autonomy I want by area (low = ask more, high = just do it):")
        for area, level in sorted(risk.items()):
            out.append(f"- **{area}**: {level}")
        out.append("")

    # 7. Decision defaults — learned precedents.
    out.append("## Decision defaults — how I've answered past blockers")
    if precedents:
        out.append("| When blocked by | I decided | Because |")
        out.append("|---|---|---|")
        for p in precedents[:40]:
            blk = str(p.get("blocker", ""))[:80].replace("|", "/")
            dec = str(p.get("decision", "")).replace("|", "/")
            why = str(p.get("rationale", ""))[:90].replace("|", "/")
            out.append(f"| {blk} | **{dec}** | {why} |")
    else:
        out.append("_No precedents recorded yet — they accrue every time I answer a blocker, "
                   "and this section fills itself in._")
    out.append("")

    # 8. Calibrated autonomy.
    if thresholds:
        out.append("## Calibrated autonomy")
        out.append("How sure an agent must be to act for me without asking, per category "
                   "(learned from how often past calls matched mine — lower means I trust it more):")
        out.append("| Category | Confidence needed |")
        out.append("|---|---|")
        for cat, thr in sorted(thresholds.items()):
            out.append(f"| {cat} | {float(thr):.0%} |")
        out.append("")

    # 9. Drift — rules going stale.
    if drift:
        out.append("## ⚠ Drift — rules that may be going stale")
        out.append("Recent reverts/changes suggest these are no longer how I work; review them:")
        for d in drift:
            out.append(f"- {d}")
        out.append("")

    # Provenance footer — the trust signal.
    n_corr = 0
    try:
        cal = store.get_calibration() or {}
        n_corr = sum(int(v.get("total", 0)) for v in cal.values())
    except Exception:
        n_corr = 0
    bits = []
    if practices:
        bits.append(f"{len(practices)} declared practices")
    if precedents:
        bits.append(f"{len(precedents)} learned precedents")
    if n_corr:
        bits.append(f"{n_corr} recorded outcomes")
    if bits:
        out.append(f"_Modeled from {', '.join(bits)}. Steers any agent in {name} the way I would._")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
