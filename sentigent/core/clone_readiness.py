"""CloneReadiness — "how much of you is captured?" (the motivation gauge).

A single 0-100% score over real signal (never vanity), with a component breakdown
and the ONE next action that raises it most. The point: make the clone's progress
visible so each session you can watch it climb toward "ready", and always know the
highest-leverage thing to do next.

Components (weights sum to 100):
  profile_synthesized  20  — your CLAUDE.md is modeled into a structured profile
  profile_depth        20  — how rich that profile is (prefs/standards/never/ask)
  signal_volume        30  — real approve/reject/correct/revert events captured
  signal_diversity     15  — across kinds (of 4) and domains, not all one thing
  practices            15  — best practices you've declared in your playbook

Honest by construction: the only way the number climbs is by actually using the
system (working, reacting, declaring practices) — not by us inflating it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

# Saturation targets — where a component is considered "full".
_SIGNAL_FULL = 200       # decision_events for full signal_volume credit
_EPISODES_FULL = 1000    # shadowed episodes (raw vibe-coding) for full volume
_PRACTICES_FULL = 8      # declared practices for full credit
_PROFILE_FIELDS = ("preferences", "coding_standards", "never_do", "ask_when")
_KINDS = ("approve", "reject", "correct", "revert")

_WEIGHTS = {
    "profile_synthesized": 20,
    "profile_depth": 20,
    "signal_volume": 30,
    "signal_diversity": 15,
    "practices": 15,
}


@dataclass
class Component:
    key: str
    pct: float          # 0..1 of this component earned
    weight: int
    detail: str
    next_hint: str      # what raises it

    @property
    def earned(self) -> float:
        return self.pct * self.weight


@dataclass
class CloneReadiness:
    percent: int                       # 0..100 overall
    components: list[Component] = field(default_factory=list)
    next_action: str = ""              # the single highest-leverage move
    stage: str = ""                    # human label for the percent

    def to_dict(self) -> dict:
        return {
            "percent": self.percent,
            "stage": self.stage,
            "next_action": self.next_action,
            "components": [
                {"key": c.key, "pct": round(c.pct, 2), "weight": c.weight,
                 "earned": round(c.earned, 1), "detail": c.detail}
                for c in self.components
            ],
        }


def _stage(pct: int) -> str:
    if pct >= 85:
        return "Clone ready — it can act as you on familiar work"
    if pct >= 60:
        return "Strong likeness — trust it on low-risk steps"
    if pct >= 35:
        return "Taking shape — keep feeding it real decisions"
    if pct >= 15:
        return "Early sketch — the foundation is in"
    return "Just born — needs your signal"


def _log_sat(n: int, full: int) -> float:
    """Saturating curve: fast early credit, asymptotes to 1.0 at `full`."""
    if n <= 0:
        return 0.0
    return min(1.0, math.log1p(n) / math.log1p(full))


def compute(store: Any) -> CloneReadiness:
    """Compute readiness from the live store. Never raises — missing data = 0."""
    # --- profile signals ---
    try:
        latest = store.get_latest_operator_profile()
    except Exception:
        latest = None
    profile = {}
    synthesized = 0.0
    if latest:
        try:
            profile = json.loads(latest.get("profile_json", "{}"))
        except Exception:
            profile = {}
        synthesized = 1.0 if latest.get("source") == "llm" else 0.4

    filled = sum(1 for k in _PROFILE_FIELDS if profile.get(k))
    has_rt = 1 if (profile.get("risk_tolerance")) else 0
    depth = (filled + has_rt) / (len(_PROFILE_FIELDS) + 1)

    # --- decision signal ---
    # Volume = how much the clone has watched. The broad signal is `episodes`
    # (one row per observed action — the real vibe-coding shadow); the narrow,
    # higher-density signal is explicit decision_events (approve/reject/...).
    # Credit the LARGER of the two so a big episode corpus counts, while explicit
    # decisions still earn volume on their own.
    try:
        counts = store.get_decision_event_counts() or {}
    except Exception:
        counts = {}
    try:
        episodes = int(store.count_episodes())
    except Exception:
        episodes = 0
    total_events = sum(int(v) for v in counts.values())
    volume = max(_log_sat(episodes, _EPISODES_FULL), _log_sat(total_events, _SIGNAL_FULL))
    kinds_present = sum(1 for k in _KINDS if counts.get(k))
    diversity = kinds_present / len(_KINDS)

    # --- practices ---
    try:
        practices = store.get_practices(active_only=True)
    except Exception:
        practices = []
    practices_pct = _log_sat(len(practices), _PRACTICES_FULL)

    comps = [
        Component("profile_synthesized", synthesized, _WEIGHTS["profile_synthesized"],
                  "CLAUDE.md modeled into a structured profile" if synthesized >= 1.0
                  else "profile not synthesized from your rules yet",
                  "run `build_profile.py` to model your CLAUDE.md"),
        Component("profile_depth", depth, _WEIGHTS["profile_depth"],
                  f"{filled}/{len(_PROFILE_FIELDS)} profile sections + risk map filled",
                  "richer CLAUDE.md / more signal deepens the profile"),
        Component("signal_volume", volume, _WEIGHTS["signal_volume"],
                  f"{episodes:,} episodes shadowed + {total_events} explicit decisions",
                  "just keep working — every action you take is captured automatically"),
        Component("signal_diversity", diversity, _WEIGHTS["signal_diversity"],
                  f"{kinds_present}/4 decision kinds seen ({', '.join(k for k in _KINDS if counts.get(k)) or 'none yet'})",
                  "reject or correct something so it learns your 'no', not just your 'yes'"),
        Component("practices", practices_pct, _WEIGHTS["practices"],
                  f"{len(practices)} best practices declared",
                  "add a practice: `practice.py add \"tests before commit\"`"),
    ]

    percent = int(round(sum(c.earned for c in comps)))
    # Highest-leverage next move = component with the most unearned weight.
    nxt = max(comps, key=lambda c: c.weight - c.earned)
    return CloneReadiness(
        percent=percent, components=comps, stage=_stage(percent),
        next_action=nxt.next_hint,
    )


def render_bar(percent: int, width: int = 24) -> str:
    filled = int(round(width * percent / 100))
    return "█" * filled + "░" * (width - filled)
