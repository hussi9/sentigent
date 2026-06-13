"""Clone briefing — "The Clone Speaks" (the in-session voice of the clone).

A short, fast, DETERMINISTIC markdown briefing the clone emits to you where you
already live (the Claude Code SessionStart hook) and on demand (the clone_briefing
MCP tool). It reads ONLY local SQLite — no LLM, no network — so it never blocks
session start. The emotional job: every session, the clone greets you, shows how
much of you it's captured, names one thing it noticed, and gives one next move.

This is the answer to "how do we interface with the user": the clone talks to you
in-session, here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sentigent.core import clone_readiness, profile_review


def build_engagement_line(store: Any) -> str:
    """A one-glance proof that Sentigent is LIVE and actively judging — the
    answer to "is the MCP even engaged?". Reads ONLY local SQLite (fast, no
    network). Shows last-24h activity, lifetime decision volume, and the
    intervention breakdown that proves it judges rather than rubber-stamps.
    Returns '' if the brain is empty or unreadable (never raises)."""
    try:
        lifetime = store.count_episodes()
        if not lifetime:
            return ""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        last24 = store.count_episodes_since(cutoff)
        by_decision = store.count_episodes_by_decision()
    except Exception:
        return ""

    # Active interventions = anything that wasn't a clean "proceed".
    enrich = by_decision.get("enrich", 0)
    slow = by_decision.get("slow_down", 0)
    esc = by_decision.get("escalate", 0)
    interventions = enrich + slow + esc

    lines = [
        "## ⚡ Sentigent is live",
        "*Judging every Bash · Edit · Write · Agent before it runs — "
        "silent unless something needs your eyes.*",
        "",
        f"- **Watching now:** {last24:,} actions checked in the last 24h",
        f"- **Brain:** {lifetime:,} decisions recorded",
    ]
    if interventions:
        parts = []
        if enrich:
            parts.append(f"{enrich:,} enrich")
        if slow:
            parts.append(f"{slow:,} slow-down")
        if esc:
            parts.append(f"{esc:,} escalate")
        lines.append(
            f"- **It doesn't rubber-stamp:** {interventions:,} interventions "
            f"({' · '.join(parts)})"
        )
    lines.append("- _See for yourself: `sentigent_score()` · `sentigent_insights()`._")
    lines.append("")

    return "\n".join(lines).strip()


def build_clone_briefing(store: Any) -> str:
    """Return a compact markdown briefing, or '' if there's nothing yet to say.
    Never raises; deterministic; safe to run on the SessionStart hot path."""
    # Nothing captured yet (or a broken store) — stay silent rather than nag.
    try:
        has_profile = store.get_latest_operator_profile() is not None
        has_practices = bool(store.get_practices(active_only=False))
        has_signal = bool(store.get_decision_event_counts())
    except Exception:
        return ""
    if not (has_profile or has_practices or has_signal):
        return ""

    try:
        r = clone_readiness.compute(store)
    except Exception:
        return ""

    bar = clone_readiness.render_bar(r.percent, 18)
    lines: list[str] = [
        f"## 🧬 Your clone — {r.percent}% ready  `{bar}`",
        f"*{r.stage}*",
        "",
    ]

    # Deterministic review (no LLM): a strength + the top gap.
    try:
        rev = profile_review.review(store, use_llm=False)
    except Exception:
        rev = None

    if rev:
        if rev.good:
            strengths = "; ".join(i.text for i in rev.good[:2])
            lines.append(f"- **What I've learned about you:** {strengths}")
        if rev.gaps:
            g = rev.gaps[0]
            lines.append(
                f"- **Biggest gap:** {g.statement} _(adopt it: `clone_adopt(1)`)_"
            )
        lines.append(f"- **Best-practice coverage:** {rev.coverage_pct}%")

    # The one next move that grows the clone most.
    lines.append(f"- **Grow me:** {r.next_action}")

    # RunDigest (E3): if the operator left an open escalation, surface it here so
    # you see it where you live. Fully optional + fail-soft — if the store lacks
    # the method or errors, skip silently. No LLM, no network.
    try:
        open_escalations = store.get_open_escalations(None)
    except Exception:
        open_escalations = []
    if open_escalations:
        esc = open_escalations[0]
        esc_id = esc.get("id")
        question = (esc.get("question") or "").strip()[:70]
        lines.append(
            f"- **Operator waiting on you:** escalation #{esc_id} — {question} "
            f'_(answer: `operator_answer({esc_id}, "approve|skip|takeover")`)_'
        )

    lines.append("")
    lines.append("_Talk to your clone in-session: `clone_status`, `clone_review`, `clone_adopt(N)`._")

    out = "\n".join(lines).strip()
    return out if len(out) > 40 else ""
