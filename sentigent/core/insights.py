"""InsightsEngine — translates raw SQLite episode data into structured findings.

Computes Brier Score, score-outcome correlations, trends, and anomalies.
Stores results in computed_insights table for instant retrieval.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class Insight:
    category: str
    subject: str
    finding: str
    confidence: float
    recommendation: str
    signal_weight: float = 0.0


@dataclass
class SessionReview:
    good_decisions: list[dict] = field(default_factory=list)
    concerns: list[dict] = field(default_factory=list)
    session_score: float = 0.0
    top_insight: str = ""
    brier_score: float = 0.0
    total_reviewed: int = 0


class InsightsEngine:
    """Computes and caches structured insights from episodic memory."""

    _GOOD_PAIRS = {("escalate", "incorrect"), ("proceed", "correct")}
    _CONCERN_PAIRS = {("proceed", "incorrect"), ("escalate", "correct")}

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def refresh_if_stale(self) -> None:
        """Recompute all insights and persist to DB."""
        try:
            episodes = self._store.get_episodes_for_insights(limit=2000)
            if len(episodes) < 5:
                return

            all_insights: list[Insight] = []
            all_insights.extend(self.compute_correlations(episodes))
            all_insights.extend(self.detect_trends(episodes))
            all_insights.extend(self.detect_anomalies(episodes))

            bs = self._brier_score(episodes)
            interpretation = (
                "well-calibrated" if bs < 0.15
                else "moderately calibrated" if bs < 0.25
                else "poorly calibrated"
            )
            all_insights.append(Insight(
                category="metric",
                subject="calibration",
                finding=f"Brier Score = {bs:.3f} ({interpretation})",
                confidence=1.0 if len(episodes) > 50 else 0.6,
                recommendation=(
                    "Record more outcomes to improve calibration"
                    if bs > 0.25 else "Judgment scores are reliable predictors"
                ),
            ))

            for insight in all_insights:
                self._store.store_computed_insight(
                    category=insight.category,
                    subject=insight.subject,
                    finding=insight.finding,
                    confidence=insight.confidence,
                    recommendation=insight.recommendation,
                    signal_weight=insight.signal_weight,
                )

            logger.info("InsightsEngine: stored %d insights", len(all_insights))
        except Exception as exc:
            logger.warning("InsightsEngine.refresh_if_stale failed: %s", exc)

    def get_cached_insights(self) -> list[Insight]:
        """Return previously computed insights from DB (no recompute)."""
        rows = self._store.get_computed_insights()
        return [
            Insight(
                category=r["category"],
                subject=r["subject"],
                finding=r["finding"],
                confidence=r["confidence"],
                recommendation=r["recommendation"],
                signal_weight=r["signal_weight"],
            )
            for r in rows
        ]

    def compute_correlations(self, episodes: list[dict] | None = None) -> list[Insight]:
        """Find tool-outcome correlations and score-decile lift."""
        if episodes is None:
            episodes = self._store.get_episodes_for_insights()
        if len(episodes) < 5:
            return []

        insights: list[Insight] = []
        by_tool: dict[str, list[dict]] = {}
        for ep in episodes:
            tool = ep.get("tool_name") or "unknown"
            by_tool.setdefault(tool, []).append(ep)

        for tool, eps in by_tool.items():
            if len(eps) < 5:
                continue
            correct = sum(1 for e in eps if e["outcome"] == "correct")
            incorrect = sum(1 for e in eps if e["outcome"] == "incorrect")
            total = correct + incorrect
            if total == 0:
                continue
            rate = correct / total
            confidence = min(0.95, 0.5 + total * 0.02)

            high_score = [e for e in eps if e["confidence"] >= 0.7]
            low_score = [e for e in eps if e["confidence"] < 0.5]
            lift_note = ""
            signal_weight = 0.0
            if len(high_score) >= 3 and len(low_score) >= 3:
                high_rate = sum(1 for e in high_score if e["outcome"] == "correct") / len(high_score)
                low_rate = sum(1 for e in low_score if e["outcome"] == "correct") / len(low_score)
                if high_rate - low_rate > 0.2:
                    lift_note = (
                        f" High-score (>=0.7): {high_rate:.0%} correct vs"
                        f" low-score (<0.5): {low_rate:.0%}."
                    )
                    signal_weight = high_rate - low_rate

            insights.append(Insight(
                category="correlation",
                subject=tool,
                finding=f"{tool}: {rate:.0%} correct ({correct}/{total} outcomes).{lift_note}",
                confidence=round(confidence, 2),
                recommendation=(
                    f"Trust {tool} operations when judgment_score >= 0.7"
                    if signal_weight > 0.2
                    else f"Monitor {tool} — {rate:.0%} success rate"
                ),
                signal_weight=round(signal_weight, 3),
            ))

        return insights

    def detect_trends(
        self,
        episodes: list[dict] | None = None,
        window_days: int = 7,
        _now: datetime | None = None,
    ) -> list[Insight]:
        """Detect improving or declining correct rates over recent window."""
        if episodes is None:
            episodes = self._store.get_episodes_for_insights()

        now = _now if _now is not None else datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=window_days)).isoformat()

        recent = [e for e in episodes if e["timestamp"] >= cutoff]
        older = [e for e in episodes if e["timestamp"] < cutoff]

        if len(recent) < 5 or len(older) < 5:
            return []

        def correct_rate(eps: list[dict]) -> float:
            denom = sum(1 for e in eps if e["outcome"] in ("correct", "incorrect"))
            if denom == 0:
                return 0.5
            return sum(1 for e in eps if e["outcome"] == "correct") / denom

        recent_rate = correct_rate(recent)
        older_rate = correct_rate(older)
        delta = recent_rate - older_rate

        if abs(delta) < 0.05:
            return []

        direction = "improving" if delta > 0 else "declining"
        confidence = min(0.9, 0.5 + min(len(recent), len(older)) * 0.02)

        return [Insight(
            category="trend",
            subject="correct_rate",
            finding=(
                f"Correct rate is {direction} over last {window_days} days: "
                f"{older_rate:.0%} -> {recent_rate:.0%} ({delta:+.0%} change)."
            ),
            confidence=round(confidence, 2),
            recommendation=(
                "Performance trending up — patterns reinforcing well"
                if delta > 0
                else "Performance declining — review recent decisions"
            ),
        )]

    def detect_anomalies(self, episodes: list[dict] | None = None) -> list[Insight]:
        """Detect sudden spikes in escalation or error rates in last 10 episodes."""
        if episodes is None:
            episodes = self._store.get_episodes_for_insights()
        if len(episodes) < 15:
            return []

        recent_10 = episodes[:10]
        rest = episodes[10:]

        def escalation_rate(eps: list[dict]) -> float:
            if not eps:
                return 0.0
            return sum(1 for e in eps if e["decision"] == "escalate") / len(eps)

        def error_rate(eps: list[dict]) -> float:
            scored = [e for e in eps if e["outcome"] in ("correct", "incorrect")]
            if not scored:
                return 0.0
            return sum(1 for e in scored if e["outcome"] == "incorrect") / len(scored)

        insights: list[Insight] = []
        recent_esc = escalation_rate(recent_10)
        overall_esc = escalation_rate(rest)

        if recent_esc > overall_esc + 0.3 and recent_esc > 0.4:
            insights.append(Insight(
                category="anomaly",
                subject="escalation_rate",
                finding=(
                    f"Escalation spike: {recent_esc:.0%} of last 10 decisions escalated"
                    f" vs {overall_esc:.0%} baseline."
                ),
                confidence=0.8,
                recommendation=(
                    "Review recent actions — high escalation may indicate a new risky pattern."
                ),
            ))

        recent_err = error_rate(recent_10)
        overall_err = error_rate(rest)
        if recent_err > overall_err + 0.25 and recent_err > 0.4:
            insights.append(Insight(
                category="anomaly",
                subject="error_rate",
                finding=(
                    f"Error spike: {recent_err:.0%} incorrect in last 10"
                    f" vs {overall_err:.0%} baseline."
                ),
                confidence=0.75,
                recommendation=(
                    "High recent error rate — agent may be in unfamiliar context."
                ),
            ))

        return insights

    def compute_session_review(self, last_n: int = 50) -> SessionReview:
        """Classify recent decisions as good or concerning."""
        episodes = self._store.get_episodes_for_insights(limit=last_n)
        if not episodes:
            return SessionReview()

        good: list[dict] = []
        concerns: list[dict] = []

        for ep in episodes[:last_n]:
            outcome = ep.get("outcome")
            decision = ep.get("decision", "")
            if not outcome:
                continue
            pair = (decision, outcome)
            entry = {
                "task": ep["task"][:80],
                "tool": ep["tool_name"],
                "decision": decision,
                "outcome": outcome,
                "confidence": round(ep["confidence"], 2),
            }
            if pair in self._GOOD_PAIRS:
                good.append(entry)
            elif pair in self._CONCERN_PAIRS:
                concerns.append(entry)

        total = len(good) + len(concerns)
        session_score = len(good) / total if total > 0 else 0.5
        brier = self._brier_score(episodes)
        cached = self.get_cached_insights()
        top = next((i.recommendation for i in cached if i.confidence > 0.8), "")

        return SessionReview(
            good_decisions=good[:10],
            concerns=concerns[:10],
            session_score=round(session_score, 3),
            top_insight=top,
            brier_score=round(brier, 3),
            total_reviewed=total,
        )

    def _brier_score(self, episodes: list[dict]) -> float:
        """Brier Score: mean((confidence - outcome_binary)^2). Lower = better."""
        scored = [e for e in episodes if e["outcome"] in ("correct", "incorrect")]
        if len(scored) < 3:
            return 0.25
        total = sum(
            (ep["confidence"] - (1.0 if ep["outcome"] == "correct" else 0.0)) ** 2
            for ep in scored
        )
        return total / len(scored)
