"""Chain circuit-breaker — stop low-confidence auto-applies from compounding (D-021).

Launch feedback (r/LLMDevs): the clone's agreement isn't 100%, and the dangerous calls are the
*borderline* ones that only just clear the confidence floor. Singly they're fine; chained, a run
of barely-confident auto-applies can drift into a pile of small wrong decisions before a human
ever sees it.

This makes those borderline calls first-class:
  • `is_borderline` — did the clone clear the bar, but only just? (floor ≤ conf < floor+margin)
  • `ChainGuard`    — track consecutive borderline auto-applies; TRIP after too many in a row so
                      the chain becomes one human checkpoint instead of silent drift, and keep a
                      reviewable trail of every borderline call for the flight summary.

Pure + deterministic. A confident call resets the streak (it breaks the chain); the trail keeps
every borderline call regardless.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_BORDERLINE_MARGIN = 0.10   # within this band above the floor counts as "borderline"
DEFAULT_MAX_CONSECUTIVE = 3        # this many borderline auto-applies in a row → pause for a human


def is_borderline(confidence: float, threshold: float,
                  margin: float = DEFAULT_BORDERLINE_MARGIN) -> bool:
    """True if the clone cleared the bar but only just: threshold ≤ confidence < threshold+margin.
    Below threshold it wouldn't have been auto-applied at all; well above is a confident call."""
    try:
        c = float(confidence)
        t = float(threshold)
    except (TypeError, ValueError):
        return False
    return t <= c < (t + max(0.0, margin))


@dataclass
class ChainGuard:
    """Tracks consecutive borderline auto-applies within a single run."""
    max_consecutive: int = DEFAULT_MAX_CONSECUTIVE
    margin: float = DEFAULT_BORDERLINE_MARGIN
    streak: int = 0
    trail: list = field(default_factory=list)   # every borderline call, for the reviewable digest

    def __post_init__(self) -> None:
        self.max_consecutive = max(1, int(self.max_consecutive))

    def record(self, *, step: int, confidence: float, threshold: float,
               category: str = "") -> bool:
        """Record one auto-applied decision. Returns True iff the breaker should TRIP now
        (i.e. this borderline call completes a streak of `max_consecutive`). A confident call
        resets the streak and returns False."""
        if is_borderline(confidence, threshold, self.margin):
            self.streak += 1
            self.trail.append({
                "step": step,
                "confidence": round(float(confidence), 2),
                "threshold": round(float(threshold), 2),
                "category": category,
            })
            return self.streak >= self.max_consecutive
        self.streak = 0
        return False

    def reset(self) -> None:
        """Clear the consecutive streak (e.g. after a human checkpoint). Keeps the trail."""
        self.streak = 0
