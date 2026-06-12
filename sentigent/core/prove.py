"""Proof of Value engine — governance reporting across agents and orgs.

Answers the key question: "Is Sentigent actually working?"

Metrics computed:
- confirmed_catches: non-proceed decisions with outcome=correct
  (Sentigent intervened and the outcome validated it was right)
- false_negatives: proceed decisions with outcome=incorrect
  (Sentigent cleared something that later failed)
- safe_passes: proceed decisions with outcome=correct
- intervention_accuracy: confirmed_catches / (confirmed_catches + wrong_interventions)
- governance_coverage: % of decisions where a policy fired
- score_trajectory: judgment score by week
- policy_enforcement: per-policy violation counts (Layer 2)
- org_compliance: per-agent compliance rate across org (Layer 2)
- top_catches: the most impactful interventions with context
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class TopCatch:
    """A single notable intervention that proved valuable."""

    timestamp: str
    task: str
    decision: str
    reason: str
    confidence: float
    tool: str = ""
    policy_name: str = ""
    source: str = "agent"  # 'agent' or 'policy'


@dataclass
class ScorePoint:
    """Judgment score at a point in time."""

    period: str    # YYYY-MM or YYYY-WW
    correct: int
    incorrect: int
    total_rated: int
    score: float


@dataclass
class PolicyStat:
    """Stats for a single org policy."""

    policy_name: str
    trigger_count: int
    confirmed_correct: int
    severity: str
    enforce_action: str


@dataclass
class AgentCompliance:
    """Per-agent compliance metrics."""

    agent_id: str
    total_episodes: int
    policy_hits: int
    confirmed_catches: int
    false_negatives: int
    score: float


@dataclass
class ProofReport:
    """Full proof-of-value report."""

    # Core proof numbers
    total_episodes: int = 0
    confirmed_catches: int = 0       # intervened + outcome=correct
    false_negatives: int = 0         # cleared + outcome=incorrect
    safe_passes: int = 0             # cleared + outcome=correct
    wrong_interventions: int = 0     # intervened + outcome=incorrect

    # Rates
    intervention_accuracy: float = 0.0   # catches / (catches + wrong_interventions)
    false_negative_rate: float = 0.0     # fn / (fn + safe_passes)
    intervention_rate: float = 0.0       # (catches+wrong) / total_with_outcomes

    # Score over time
    score_trajectory: list[ScorePoint] = field(default_factory=list)

    # Layer 2 policy stats
    policy_stats: list[PolicyStat] = field(default_factory=list)
    total_policy_enforcements: int = 0

    # Per-agent breakdown (Layer 2)
    agent_compliance: list[AgentCompliance] = field(default_factory=list)

    # Top catches for storytelling
    top_catches: list[TopCatch] = field(default_factory=list)

    # Phase 6A: Conversation intelligence section
    conversation_intelligence: dict[str, Any] = field(default_factory=dict)
    estimated_monthly_savings_usd: float = 0.0

    # Summary
    verdict: str = ""
    org_id: str = ""
    agent_id: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_episodes": self.total_episodes,
            "confirmed_catches": self.confirmed_catches,
            "false_negatives": self.false_negatives,
            "safe_passes": self.safe_passes,
            "wrong_interventions": self.wrong_interventions,
            "intervention_accuracy": round(self.intervention_accuracy, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "intervention_rate": round(self.intervention_rate, 4),
            "score_trajectory": [
                {
                    "period": p.period,
                    "correct": p.correct,
                    "incorrect": p.incorrect,
                    "total_rated": p.total_rated,
                    "score": round(p.score, 4),
                }
                for p in self.score_trajectory
            ],
            "policy_stats": [
                {
                    "policy_name": p.policy_name,
                    "trigger_count": p.trigger_count,
                    "confirmed_correct": p.confirmed_correct,
                    "severity": p.severity,
                    "enforce_action": p.enforce_action,
                }
                for p in self.policy_stats
            ],
            "total_policy_enforcements": self.total_policy_enforcements,
            "agent_compliance": [
                {
                    "agent_id": a.agent_id,
                    "total_episodes": a.total_episodes,
                    "policy_hits": a.policy_hits,
                    "confirmed_catches": a.confirmed_catches,
                    "false_negatives": a.false_negatives,
                    "score": round(a.score, 4),
                }
                for a in self.agent_compliance
            ],
            "top_catches": [
                {
                    "timestamp": c.timestamp,
                    "task": c.task,
                    "decision": c.decision,
                    "reason": c.reason,
                    "confidence": round(c.confidence, 3),
                    "tool": c.tool,
                    "policy_name": c.policy_name,
                    "source": c.source,
                }
                for c in self.top_catches
            ],
            "verdict": self.verdict,
            "org_id": self.org_id,
            "agent_id": self.agent_id,
            "generated_at": self.generated_at,
            "conversation_intelligence": self.conversation_intelligence,
            "estimated_monthly_savings_usd": round(self.estimated_monthly_savings_usd, 2),
        }

    def to_text(self) -> str:
        """Human-readable proof report for terminal output."""
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            "║         SENTIGENT — PROOF OF VALUE REPORT                ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]

        # Verdict banner
        if self.intervention_accuracy >= 0.9:
            lines.append(f"  ✅  VERDICT: {self.verdict}")
        elif self.intervention_accuracy >= 0.7:
            lines.append(f"  ⚠️   VERDICT: {self.verdict}")
        else:
            lines.append(f"  ❌  VERDICT: {self.verdict}")

        lines += [
            "",
            f"  Agent: {self.agent_id}  |  Org: {self.org_id}  |  Generated: {self.generated_at[:10]}",
            "",
            "  ── Core Numbers ──────────────────────────────────────────",
            f"  Total decisions tracked    : {self.total_episodes:>6,}",
            f"  Confirmed catches          : {self.confirmed_catches:>6,}  "
            f"(intervened → outcome was correct)",
            f"  False negatives            : {self.false_negatives:>6,}  "
            f"(cleared → outcome was wrong)",
            f"  Safe passes                : {self.safe_passes:>6,}  "
            f"(cleared → outcome was correct)",
            "",
            f"  Intervention accuracy      : {self.intervention_accuracy:>6.1%}  "
            f"(when Sentigent intervenes, it's right this % of the time)",
            f"  False negative rate        : {self.false_negative_rate:>6.1%}  "
            f"(this % of bad actions slipped through)",
            f"  Intervention rate          : {self.intervention_rate:>6.1%}  "
            f"(Sentigent flags this % of all decisions)",
            "",
        ]

        # Score trajectory
        if self.score_trajectory:
            lines.append("  ── Judgment Score Over Time ──────────────────────────────")
            for pt in self.score_trajectory[-8:]:
                bar_len = int(pt.score * 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                lines.append(f"  {pt.period}  [{bar}]  {pt.score:.1%}  (n={pt.total_rated})")
            lines.append("")

        # Policy enforcement
        if self.policy_stats:
            lines.append("  ── Org Policy Enforcement ────────────────────────────────")
            lines.append(f"  {'Policy':<30} {'Action':<12} {'Triggers':>8} {'Severity':<10}")
            lines.append("  " + "─" * 65)
            for p in sorted(self.policy_stats, key=lambda x: -x.trigger_count):
                lines.append(
                    f"  {p.policy_name:<30} {p.enforce_action:<12} "
                    f"{p.trigger_count:>8} {p.severity:<10}"
                )
            lines.append(f"\n  Total enforcements: {self.total_policy_enforcements:,}")
            lines.append("")

        # Agent compliance
        if self.agent_compliance:
            lines.append("  ── Agent Compliance (Org View) ───────────────────────────")
            lines.append(f"  {'Agent':<20} {'Score':>6} {'Episodes':>9} {'Policy Hits':>12}")
            lines.append("  " + "─" * 50)
            for a in sorted(self.agent_compliance, key=lambda x: -x.score):
                lines.append(
                    f"  {a.agent_id:<20} {a.score:>6.1%} {a.total_episodes:>9,} {a.policy_hits:>12,}"
                )
            lines.append("")

        # Top catches
        if self.top_catches:
            lines.append("  ── Top Catches (Sentigent Saved These) ──────────────────")
            for i, c in enumerate(self.top_catches[:5], 1):
                ts = c.timestamp[:16].replace("T", " ")
                task_short = c.task[:70] + "…" if len(c.task) > 70 else c.task
                lines += [
                    f"\n  #{i} [{ts}]  {c.decision.upper()}",
                    f"     Task   : {task_short}",
                    f"     Reason : {c.reason[:80]}",
                ]
                if c.policy_name:
                    lines.append(f"     Policy : {c.policy_name}")
            lines.append("")

        return "\n".join(lines)


# ── Proof Engine ──────────────────────────────────────────────


class ProofEngine:
    """Compute proof-of-value metrics from local SQLite + Supabase Layer 2.

    Pulls local episodes for individual agent stats, and org data from
    Supabase for the full governance picture.
    """

    def __init__(self, agent_id: str, org_id: str, db_path: str | None = None) -> None:
        self.agent_id = agent_id
        self.org_id = org_id
        if db_path:
            self._db_path = db_path
        else:
            self._db_path = str(
                Path.home() / ".sentigent" / f"memory_{agent_id}.db"
            )

    def _get_conn(self) -> sqlite3.Connection | None:
        p = Path(self._db_path)
        if not p.exists():
            return None
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_supabase(self) -> Any:
        try:
            import os
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL", "")
            key = (
                os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                or os.environ.get("SUPABASE_ANON_KEY", "")
            )
            if url and key:
                return create_client(url, key)
        except Exception:
            pass
        return None

    def compute(self, days: int = 90) -> ProofReport:
        """Compute the full proof-of-value report."""
        report = ProofReport(
            agent_id=self.agent_id,
            org_id=self.org_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        conn = self._get_conn()
        if conn:
            try:
                self._compute_local(conn, report, days)
            finally:
                conn.close()

        # Enrich with Layer 2 data
        self._compute_layer2(report)

        # Phase 6A: Enrich with conversation intelligence (outcome attribution)
        self._compute_conversation_intelligence(report, days)

        # Set verdict
        report.verdict = self._verdict(report)
        return report

    def _compute_conversation_intelligence(self, report: ProofReport, days: int) -> None:
        """Compute conversation intelligence section via OutcomeAttributor (Phase 6A)."""
        try:
            from sentigent.core.outcome_attributor import OutcomeAttributor
            db_path = self._get_db_path()
            if not db_path:
                return
            attr = OutcomeAttributor(
                db_path=db_path,
                agent_id=self.agent_id,
                org_id=self.org_id,
            )
            attr_report = attr.analyze(days=days)
            report.conversation_intelligence = attr_report.conversation_intelligence
            report.estimated_monthly_savings_usd = attr_report.estimated_monthly_savings_usd
        except Exception:
            pass  # Fails open

    def _get_db_path(self) -> str:
        """Return the SQLite DB path used by MemoryStore for this agent."""
        try:
            import os
            from pathlib import Path
            db_dir = Path(
                os.environ.get("SENTIGENT_DB_DIR", Path.home() / ".sentigent")
            )
            return str(db_dir / f"{self.agent_id}.db")
        except Exception:
            return ""

    def _compute_local(
        self, conn: sqlite3.Connection, report: ProofReport, days: int,
    ) -> None:
        """Compute individual agent metrics from local SQLite."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        rows = conn.execute(
            """
            SELECT task, decision, outcome, confidence_at_decision,
                   reason, context, timestamp
            FROM episodes
            WHERE agent_id = ? AND timestamp >= ? AND outcome IS NOT NULL
            ORDER BY timestamp DESC
            """,
            (self.agent_id, cutoff),
        ).fetchall()

        report.total_episodes = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND timestamp >= ?",
            (self.agent_id, cutoff),
        ).fetchone()[0]

        catches: list[TopCatch] = []

        for row in rows:
            decision = row["decision"] or "proceed"
            outcome = row["outcome"] or ""
            is_intervention = decision in ("slow_down", "escalate", "enrich", "block")

            if is_intervention and outcome == "correct":
                report.confirmed_catches += 1
                # Extract tool name from context
                ctx: dict = {}
                try:
                    ctx = json.loads(row["context"]) if row["context"] else {}
                except Exception:
                    pass
                catches.append(TopCatch(
                    timestamp=row["timestamp"] or "",
                    task=row["task"] or "",
                    decision=decision,
                    reason=row["reason"] or "",
                    confidence=float(row["confidence_at_decision"] or 0.5),
                    tool=ctx.get("tool_name", ""),
                ))
            elif not is_intervention and outcome == "incorrect":
                report.false_negatives += 1
            elif not is_intervention and outcome == "correct":
                report.safe_passes += 1
            elif is_intervention and outcome == "incorrect":
                report.wrong_interventions += 1

        # Rates
        total_interventions = report.confirmed_catches + report.wrong_interventions
        total_passes = report.safe_passes + report.false_negatives
        total_rated = total_interventions + total_passes

        report.intervention_accuracy = (
            report.confirmed_catches / total_interventions
            if total_interventions > 0 else 0.0
        )
        report.false_negative_rate = (
            report.false_negatives / total_passes
            if total_passes > 0 else 0.0
        )
        report.intervention_rate = (
            total_interventions / total_rated if total_rated > 0 else 0.0
        )

        # Score trajectory by month
        by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "incorrect": 0, "total": 0})
        for row in rows:
            month = (row["timestamp"] or "")[:7]
            if not month:
                continue
            by_month[month]["total"] += 1
            if row["outcome"] == "correct":
                by_month[month]["correct"] += 1
            elif row["outcome"] == "incorrect":
                by_month[month]["incorrect"] += 1

        report.score_trajectory = sorted([
            ScorePoint(
                period=month,
                correct=stats["correct"],
                incorrect=stats["incorrect"],
                total_rated=stats["total"],
                score=stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0,
            )
            for month, stats in by_month.items()
        ], key=lambda x: x.period)

        # Top catches — sorted by confidence desc (high confidence interventions are more impressive)
        report.top_catches = sorted(catches, key=lambda c: -c.confidence)[:10]

    def _compute_layer2(self, report: ProofReport) -> None:
        """Enrich report with org-wide data from Supabase."""
        client = self._get_supabase()
        if not client:
            return

        try:
            # Policy stats
            result = (
                client.table("org_policies")
                .select("policy_name,trigger_count,severity,enforce_action,is_active")
                .eq("org_id", self.org_id)
                .execute()
            )
            policy_stats = []
            total_enforcements = 0
            for row in (result.data or []):
                tc = int(row.get("trigger_count") or 0)
                total_enforcements += tc
                # Get confirmed correct count from violations table
                try:
                    vc = client.table("policy_violations").select(
                        "id", count="exact"
                    ).eq("org_id", self.org_id).eq(
                        "policy_name", row["policy_name"]
                    ).eq("confirmed_correct", True).execute()
                    confirmed = vc.count or 0
                except Exception:
                    confirmed = 0
                policy_stats.append(PolicyStat(
                    policy_name=row.get("policy_name", ""),
                    trigger_count=tc,
                    confirmed_correct=confirmed,
                    severity=row.get("severity", "medium"),
                    enforce_action=row.get("enforce_action", "slow_down"),
                ))
            report.policy_stats = policy_stats
            report.total_policy_enforcements = total_enforcements

        except Exception as exc:
            pass  # Layer 2 unavailable — local-only report

        try:
            # Per-agent breakdown
            eps_result = (
                client.table("synced_episodes")
                .select("agent_id,outcome")
                .eq("org_id", self.org_id)
                .execute()
            )
            agents: dict[str, dict[str, int]] = defaultdict(
                lambda: {"total": 0, "correct": 0, "incorrect": 0}
            )
            for row in (eps_result.data or []):
                aid = row.get("agent_id", "unknown")
                agents[aid]["total"] += 1
                outcome = row.get("outcome") or ""
                if outcome in ("correct", "incorrect"):
                    agents[aid][outcome] += 1

            # Violations per agent
            viol_result = (
                client.table("policy_violations")
                .select("agent_id")
                .eq("org_id", self.org_id)
                .execute()
            )
            violations_by_agent: dict[str, int] = defaultdict(int)
            for row in (viol_result.data or []):
                violations_by_agent[row.get("agent_id", "")] += 1

            compliance_list = []
            for aid, stats in agents.items():
                total_rated = stats["correct"] + stats["incorrect"]
                score = stats["correct"] / total_rated if total_rated > 0 else 0.0
                compliance_list.append(AgentCompliance(
                    agent_id=aid,
                    total_episodes=stats["total"],
                    policy_hits=violations_by_agent.get(aid, 0),
                    confirmed_catches=0,  # would need more joins
                    false_negatives=0,
                    score=score,
                ))
            report.agent_compliance = sorted(
                compliance_list, key=lambda a: -a.score,
            )

        except Exception:
            pass

    @staticmethod
    def _verdict(report: ProofReport) -> str:
        acc = report.intervention_accuracy
        fn_rate = report.false_negative_rate
        catches = report.confirmed_catches

        if catches == 0:
            return (
                "Not enough outcome data yet. Record outcomes after agent actions "
                "to generate proof. Run: sentigent_outcome(trace_id, 'correct')"
            )
        if acc >= 0.95 and fn_rate < 0.01:
            return (
                f"Sentigent is working excellently. {catches} confirmed catches, "
                f"{acc:.0%} intervention accuracy, {fn_rate:.1%} false negatives."
            )
        if acc >= 0.80:
            return (
                f"Sentigent is effective. {catches} confirmed catches with "
                f"{acc:.0%} accuracy. Some tuning may improve further."
            )
        if acc >= 0.60:
            return (
                f"Sentigent is learning. {catches} catches so far with "
                f"{acc:.0%} accuracy. Record more outcomes to accelerate learning."
            )
        return (
            f"Sentigent needs more outcome data. Only {catches} confirmed catches. "
            f"Use sentigent_outcome() after each operation to feed the learning loop."
        )
