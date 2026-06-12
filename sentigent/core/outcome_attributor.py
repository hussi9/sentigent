"""Phase 6A: Outcome Attributor — connect instruction clarity at T to outcomes at T+k.

Answers the question: "Does prompt quality predict agent success?"

Learns per-domain, per-specificity-bucket patterns from stored episodes:

    Episode: task="fix the auth thing", specificity=0.31, domain="auth"
    Outcome: incorrect
    → pattern: auth tasks, specificity < 0.40 → 73% incorrect rate

Over time this builds a table of:
    domain × specificity_bucket → {outcome_rate, avg_correction_loops, sample_size}

This data:
- Feeds the coaching system (suggest rewrite before acting)
- Powers the prove command Conversation Intelligence section
- Generates ROI figures ($X/month in avoided rework)

All computation is pure SQL + heuristics, no external calls.

Usage::

    from sentigent.core.outcome_attributor import OutcomeAttributor

    attr = OutcomeAttributor(db_path, agent_id, org_id)
    report = attr.analyze(days=90)
    # report["patterns"] → list of learned patterns
    # report["conversation_intelligence"] → prove command section dict
    # report["estimated_monthly_savings_usd"] → float
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# Cost assumptions for savings calculation
_COST_PER_CLARIFICATION_USD = 0.12  # avg cost of one clarification round-trip
_CLARIFICATIONS_SAVED_PER_CLEAR_TASK = 1.5  # avg saved when clarity ≥ 0.7


@dataclass
class AttributionPattern:
    """A learned pattern linking clarity/specificity to outcomes."""

    domain: str
    specificity_bucket: str          # "low" (<0.4) | "medium" (0.4–0.7) | "high" (≥0.7)
    specificity_range: tuple[float, float]
    total_episodes: int
    correct_count: int
    incorrect_count: int
    outcome_rate: float              # correct / (correct + incorrect)
    incorrect_rate: float
    avg_specificity: float
    insight: str                     # human-readable lesson

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "specificity_bucket": self.specificity_bucket,
            "total_episodes": self.total_episodes,
            "outcome_rate": round(self.outcome_rate, 3),
            "incorrect_rate": round(self.incorrect_rate, 3),
            "avg_specificity": round(self.avg_specificity, 3),
            "insight": self.insight,
        }


@dataclass
class AttributionReport:
    """Full attribution analysis result."""

    days: int
    total_episodes_analyzed: int
    episodes_with_clarity: int
    patterns: list[AttributionPattern] = field(default_factory=list)
    conversation_intelligence: dict[str, Any] = field(default_factory=dict)
    estimated_monthly_savings_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "days": self.days,
            "total_episodes_analyzed": self.total_episodes_analyzed,
            "episodes_with_clarity": self.episodes_with_clarity,
            "patterns": [p.to_dict() for p in self.patterns],
            "conversation_intelligence": self.conversation_intelligence,
            "estimated_monthly_savings_usd": round(self.estimated_monthly_savings_usd, 2),
        }


class OutcomeAttributor:
    """Correlate instruction clarity to agent outcomes from episodic memory."""

    def __init__(self, db_path: str, agent_id: str, org_id: str) -> None:
        self.db_path = db_path
        self.agent_id = agent_id
        self.org_id = org_id
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Add clarity_score + task_specificity columns if missing (safe migration)."""
        conn = sqlite3.connect(self.db_path)
        for col, dtype in [
            ("clarity_score", "REAL"),
            ("task_specificity", "REAL"),
            ("task_domain", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE episodes ADD COLUMN {col} {dtype}")
                conn.commit()
            except Exception:
                pass  # Column already exists
        conn.close()

    def backfill_clarity(self, limit: int = 500) -> int:
        """Compute clarity + specificity for episodes that don't have it yet.

        Call this once or periodically to populate historical episodes.
        Returns the number of episodes backfilled.
        """
        try:
            from sentigent.core.clarity_scorer import ClarityScorer
            from sentigent.core.intent_extractor import IntentExtractor
            from sentigent.core.context_assembler import classify_domain
        except ImportError:
            return 0

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, task
            FROM episodes
            WHERE agent_id = ? AND clarity_score IS NULL
            LIMIT ?
            """,
            (self.agent_id, limit),
        ).fetchall()

        if not rows:
            conn.close()
            return 0

        scorer = ClarityScorer()
        extractor = IntentExtractor()
        count = 0

        for row in rows:
            task = row["task"] or ""
            try:
                cs = scorer.score(task)
                intent = extractor.extract(task)
                domain = classify_domain(task)
                conn.execute(
                    """
                    UPDATE episodes
                    SET clarity_score = ?, task_specificity = ?, task_domain = ?
                    WHERE trace_id = ?
                    """,
                    (cs.overall, intent.specificity, domain, row["trace_id"]),
                )
                count += 1
            except Exception:
                continue

        conn.commit()
        conn.close()
        return count

    def analyze(self, days: int = 90) -> AttributionReport:
        """Compute attribution patterns over the look-back window.

        Args:
            days: Number of days to look back.

        Returns:
            AttributionReport with patterns and conversation intelligence section.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Total episodes in window with outcomes
        total_rows = conn.execute(
            """
            SELECT COUNT(*) as n FROM episodes
            WHERE agent_id = ? AND timestamp >= ? AND outcome IS NOT NULL
            """,
            (self.agent_id, cutoff),
        ).fetchone()
        total_episodes = total_rows["n"] if total_rows else 0

        # Episodes with clarity data
        clarity_rows = conn.execute(
            """
            SELECT trace_id, task, decision, outcome, clarity_score,
                   task_specificity, task_domain, timestamp
            FROM episodes
            WHERE agent_id = ? AND timestamp >= ?
              AND outcome IS NOT NULL AND clarity_score IS NOT NULL
            ORDER BY timestamp DESC
            """,
            (self.agent_id, cutoff),
        ).fetchall()
        conn.close()

        episodes_with_clarity = len(clarity_rows)

        if not clarity_rows:
            return AttributionReport(
                days=days,
                total_episodes_analyzed=total_episodes,
                episodes_with_clarity=0,
                conversation_intelligence={
                    "message": "No clarity data yet. Episodes will be scored on next evaluate() call.",
                    "hint": "Run sentigent_backfill_clarity() to score historical episodes.",
                },
            )

        # Group into domain × specificity_bucket
        buckets: dict[tuple[str, str], list[dict]] = {}
        for row in clarity_rows:
            domain = row["task_domain"] or "general"
            spec = row["task_specificity"] or 0.0
            if spec < 0.40:
                bucket = "low"
            elif spec < 0.70:
                bucket = "medium"
            else:
                bucket = "high"
            key = (domain, bucket)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append({
                "outcome": row["outcome"],
                "specificity": spec,
                "clarity_score": row["clarity_score"],
            })

        patterns: list[AttributionPattern] = []
        for (domain, bucket), eps in sorted(buckets.items()):
            if len(eps) < 3:
                continue  # not enough data

            correct = sum(1 for e in eps if e["outcome"] == "correct")
            incorrect = len(eps) - correct
            outcome_rate = correct / len(eps)
            incorrect_rate = incorrect / len(eps)
            avg_spec = sum(e["specificity"] for e in eps) / len(eps)

            spec_range = {"low": (0.0, 0.4), "medium": (0.4, 0.7), "high": (0.7, 1.0)}[bucket]

            insight = _generate_insight(domain, bucket, incorrect_rate, avg_spec, len(eps))
            patterns.append(AttributionPattern(
                domain=domain,
                specificity_bucket=bucket,
                specificity_range=spec_range,
                total_episodes=len(eps),
                correct_count=correct,
                incorrect_count=incorrect,
                outcome_rate=outcome_rate,
                incorrect_rate=incorrect_rate,
                avg_specificity=avg_spec,
                insight=insight,
            ))

        patterns.sort(key=lambda p: p.incorrect_rate, reverse=True)

        # Compute conversation intelligence metrics for prove command
        all_specs = [row["task_specificity"] or 0.0 for row in clarity_rows]
        all_clarity = [row["clarity_score"] or 0.0 for row in clarity_rows]
        avg_clarity_overall = sum(all_clarity) / len(all_clarity) if all_clarity else 0.0
        avg_spec_overall = sum(all_specs) / len(all_specs) if all_specs else 0.0

        # High-clarity episodes: how many avoided rework?
        high_clarity_correct = sum(
            1 for row in clarity_rows
            if (row["task_specificity"] or 0.0) >= 0.70 and row["outcome"] == "correct"
        )
        low_clarity_incorrect = sum(
            1 for row in clarity_rows
            if (row["task_specificity"] or 0.0) < 0.40 and row["outcome"] == "incorrect"
        )

        # Estimated savings: low-clarity incorrect episodes that could have been avoided
        estimated_monthly = (
            low_clarity_incorrect
            * _COST_PER_CLARIFICATION_USD
            * _CLARIFICATIONS_SAVED_PER_CLEAR_TASK
            * (30.0 / max(days, 1))
            * 720  # scale to team of 720 agent-hours/month assumption
        )
        # Cap at reasonable enterprise figure
        estimated_monthly = min(estimated_monthly, 15000.0)

        conv_intel = {
            "avg_clarity_score": round(avg_clarity_overall, 3),
            "avg_task_specificity": round(avg_spec_overall, 3),
            "high_clarity_correct_outcomes": high_clarity_correct,
            "low_clarity_incorrect_outcomes": low_clarity_incorrect,
            "estimated_rework_avoided": low_clarity_incorrect,
            "top_insight": patterns[0].insight if patterns else "Collect more episodes for insights.",
        }

        return AttributionReport(
            days=days,
            total_episodes_analyzed=total_episodes,
            episodes_with_clarity=episodes_with_clarity,
            patterns=patterns,
            conversation_intelligence=conv_intel,
            estimated_monthly_savings_usd=estimated_monthly,
        )


def _generate_insight(
    domain: str, bucket: str, incorrect_rate: float, avg_spec: float, n: int
) -> str:
    """Generate a human-readable lesson from a pattern."""
    if incorrect_rate >= 0.60:
        severity = "⚠️ High risk"
        verb = "almost always fails"
    elif incorrect_rate >= 0.35:
        severity = "⚡ Moderate risk"
        verb = "often requires rework"
    else:
        severity = "✓ Low risk"
        verb = "usually succeeds"

    return (
        f"{severity}: {domain} tasks with {bucket} specificity (avg {avg_spec:.2f}) "
        f"{verb} ({incorrect_rate*100:.0f}% incorrect, n={n})"
    )
