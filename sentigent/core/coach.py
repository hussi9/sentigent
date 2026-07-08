"""Interaction Coach — AI agent that observes patterns and suggests improvements.

Bridges two layers:
1. Statistical pre-analysis (pure Python, no AI):
   - Tool failure rates, decision accuracy, workflow sequences
2. AI synthesis (Claude Haiku):
   - Natural language suggestions for how to improve agent interactions
   - Specific prompt rewording examples
   - Workflow patterns that consistently succeed vs fail

The coach does NOT make real-time decisions — it runs periodically (on demand)
and produces a CoachingReport that can be surfaced via MCP tool or CLI.

No AI is involved in pre-analysis. AI is only used at the final synthesis step,
so the system stays auditable even when the AI layer is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sentigent.coach")


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ToolStat:
    tool: str
    total: int
    correct: int
    incorrect: int
    neutral: int

    @property
    def failure_rate(self) -> float:
        scored = self.correct + self.incorrect
        return self.incorrect / scored if scored > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Success rate among scored (non-neutral) outcomes only."""
        scored = self.correct + self.incorrect
        return self.correct / scored if scored > 0 else 0.0

    @property
    def scored(self) -> int:
        return self.correct + self.incorrect


@dataclass
class DecisionAccuracy:
    """Did Sentigent's caution (enrich/slow_down) actually matter?"""
    enrich_then_correct: int = 0
    enrich_then_incorrect: int = 0
    proceed_then_correct: int = 0
    proceed_then_incorrect: int = 0

    @property
    def enrich_saved_something(self) -> float:
        """How often did enrich decisions lead to correct outcomes."""
        total = self.enrich_then_correct + self.enrich_then_incorrect
        return self.enrich_then_correct / total if total > 0 else 0.0

    @property
    def proceed_was_safe(self) -> float:
        total = self.proceed_then_correct + self.proceed_then_incorrect
        return self.proceed_then_correct / total if total > 0 else 0.0


@dataclass
class TaskCluster:
    """A group of similar tasks with a shared outcome pattern."""
    label: str          # human-readable label e.g. "File editing operations"
    count: int
    success_rate: float
    example_tasks: list[str]
    dominant_tool: str


@dataclass
class CoachingReport:
    agent_id: str
    generated_at: str
    lookback_days: int
    tool_stats: list[ToolStat]
    decision_accuracy: DecisionAccuracy
    task_clusters: list[TaskCluster]
    suggestions: list[str]          # AI-generated
    summary: str                    # AI-generated one-liner
    raw_pattern_data: dict[str, Any] = field(default_factory=dict)
    ai_error: str = ""              # non-empty if AI synthesis failed with known error

    def to_text(self) -> str:
        lines = [
            f"\n{'='*64}",
            f"  SENTIGENT INTERACTION COACH — {self.agent_id}",
            f"  Generated: {self.generated_at[:16]}  |  Window: {self.lookback_days} days",
            f"{'='*64}\n",
            f"  SUMMARY\n  {self.summary}\n",
            f"  TOOL PERFORMANCE\n  {'─'*48}",
        ]
        for s in sorted(self.tool_stats, key=lambda x: -x.total):
            bar = "▓" * int(s.success_rate * 20) + "░" * (20 - int(s.success_rate * 20))
            n_label = f"n={s.scored}" if s.neutral > 0 else f"n={s.total}"
            lines.append(f"  {s.tool:<8}  [{bar}]  {s.success_rate:.0%} success  ({n_label} scored, {s.neutral} unscored)")

        lines += [
            f"\n  DECISION ACCURACY\n  {'─'*48}",
            f"  When Sentigent said 'enrich': {self.decision_accuracy.enrich_saved_something:.0%} led to correct outcome",
            f"  When Sentigent said 'proceed': {self.decision_accuracy.proceed_was_safe:.0%} were safe",
            f"\n  WORKFLOW PATTERNS\n  {'─'*48}",
        ]
        for cluster in self.task_clusters:
            flag = "✓" if cluster.success_rate >= 0.8 else "⚠"
            lines.append(
                f"  {flag} {cluster.label:<35} {cluster.success_rate:.0%} success (n={cluster.count})"
            )

        lines += [f"\n  AI SUGGESTIONS\n  {'─'*48}"]
        if self.ai_error:
            lines.append(f"\n  {self.ai_error}")
            lines.append("  (Showing rule-based suggestions instead)\n")
        for i, s in enumerate(self.suggestions, 1):
            # Wrap long lines
            words = s.split()
            current, wrapped = [], []
            for w in words:
                if sum(len(x) + 1 for x in current) + len(w) > 70:
                    wrapped.append("  " + " ".join(current))
                    current = [w]
                else:
                    current.append(w)
            if current:
                wrapped.append("  " + " ".join(current))
            lines.append(f"\n  {i}. {wrapped[0].strip()}")
            lines.extend(wrapped[1:])

        lines.append(f"\n{'='*64}\n")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "summary": self.summary,
            "tool_stats": [
                {
                    "tool": s.tool, "total": s.total,
                    "success_rate": round(s.success_rate, 3),
                    "failure_rate": round(s.failure_rate, 3),
                }
                for s in self.tool_stats
            ],
            "decision_accuracy": {
                "enrich_leads_to_correct": round(self.decision_accuracy.enrich_saved_something, 3),
                "proceed_is_safe": round(self.decision_accuracy.proceed_was_safe, 3),
            },
            "task_clusters": [
                {
                    "label": c.label,
                    "count": c.count,
                    "success_rate": round(c.success_rate, 3),
                    "example": c.example_tasks[0] if c.example_tasks else "",
                }
                for c in self.task_clusters
            ],
            "suggestions": self.suggestions,
        }


# ── Coach ─────────────────────────────────────────────────────────────────────

class InteractionCoach:
    """Observes agent interaction patterns and generates AI-powered suggestions."""

    def __init__(self, agent_id: str = "", db_path: str | None = None) -> None:
        if not agent_id:
            from sentigent.config import get_config
            agent_id = get_config().agent_id
        self.agent_id = agent_id
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = Path.home() / ".sentigent" / f"memory_{agent_id}.db"

    def analyze(self, lookback_days: int = 7) -> CoachingReport:
        """Run full analysis: statistics then AI synthesis."""
        self._ai_error: str = ""  # reset per run
        episodes = self._load_episodes(lookback_days)
        if len(episodes) < 5:
            return self._empty_report(lookback_days, reason=f"Only {len(episodes)} episodes in window")

        tool_stats = self._compute_tool_stats(episodes)
        decision_acc = self._compute_decision_accuracy(episodes)
        task_clusters = self._cluster_tasks(episodes)
        pattern_data = self._build_pattern_summary(tool_stats, decision_acc, task_clusters, episodes)

        suggestions, summary = self._ai_synthesize(pattern_data)

        return CoachingReport(
            agent_id=self.agent_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            lookback_days=lookback_days,
            tool_stats=tool_stats,
            decision_accuracy=decision_acc,
            task_clusters=task_clusters,
            suggestions=suggestions,
            summary=summary,
            raw_pattern_data=pattern_data,
            ai_error=getattr(self, "_ai_error", ""),
        )

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_episodes(self, lookback_days: int) -> list[dict[str, Any]]:
        if not self._db_path.exists():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT task, context, signals, decision, outcome, outcome_feedback, timestamp
                   FROM episodes WHERE timestamp >= ? AND outcome IS NOT NULL
                   ORDER BY timestamp""",
                (cutoff,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("Failed to load episodes: %s", exc)
            return []

    # ── Statistical analysis ──────────────────────────────────────────────────

    def _compute_tool_stats(self, episodes: list[dict]) -> list[ToolStat]:
        by_tool: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "incorrect": 0, "neutral": 0})
        for ep in episodes:
            tool = self._extract_tool(ep)
            outcome = ep.get("outcome", "neutral")
            by_tool[tool][outcome] = by_tool[tool].get(outcome, 0) + 1

        return [
            ToolStat(
                tool=tool,
                total=sum(counts.values()),
                correct=counts.get("correct", 0),
                incorrect=counts.get("incorrect", 0),
                neutral=counts.get("neutral", 0),
            )
            for tool, counts in by_tool.items()
        ]

    def _compute_decision_accuracy(self, episodes: list[dict]) -> DecisionAccuracy:
        acc = DecisionAccuracy()
        for ep in episodes:
            decision = ep.get("decision", "")
            outcome = ep.get("outcome", "")
            if decision in ("enrich", "slow_down"):
                if outcome == "correct":
                    acc.enrich_then_correct += 1
                elif outcome == "incorrect":
                    acc.enrich_then_incorrect += 1
            elif decision == "proceed":
                if outcome == "correct":
                    acc.proceed_then_correct += 1
                elif outcome == "incorrect":
                    acc.proceed_then_incorrect += 1
        return acc

    def _cluster_tasks(self, episodes: list[dict]) -> list[TaskCluster]:
        """Group tasks into semantic clusters using simple keyword matching."""
        clusters: dict[str, list[dict]] = defaultdict(list)

        patterns = [
            ("File editing", re.compile(r"\b(Edit|Write):", re.I)),
            ("Bash commands", re.compile(r"\bBash:", re.I)),
            ("Database operations", re.compile(r"\b(sql|psql|supabase|migrate|select|insert|update|delete)\b", re.I)),
            ("Test runs", re.compile(r"\b(pytest|jest|vitest|npm test|yarn test|cargo test)\b", re.I)),
            ("Git operations", re.compile(r"\bgit\s+(commit|push|pull|merge|rebase|checkout)\b", re.I)),
            ("Package management", re.compile(r"\b(npm|pip|yarn|pnpm)\s+(install|add|remove)\b", re.I)),
            ("File reading", re.compile(r"\b(Read|Glob|Grep):", re.I)),
            ("Web/API calls", re.compile(r"\b(curl|wget|WebFetch|fetch|requests)\b", re.I)),
            ("Deploy/publish", re.compile(r"\b(deploy|publish|release|push.*prod)\b", re.I)),
        ]

        for ep in episodes:
            task = ep.get("task", "")
            matched = False
            for label, pat in patterns:
                if pat.search(task):
                    clusters[label].append(ep)
                    matched = True
                    break
            if not matched:
                clusters["Other operations"].append(ep)

        result = []
        for label, eps in clusters.items():
            if not eps:
                continue
            correct = sum(1 for e in eps if e.get("outcome") == "correct")
            incorrect = sum(1 for e in eps if e.get("outcome") == "incorrect")
            total_scored = correct + incorrect
            success = correct / total_scored if total_scored > 0 else 0.5
            dominant_tool = Counter(self._extract_tool(e) for e in eps).most_common(1)[0][0]
            examples = [e.get("task", "")[:60] for e in eps[:2]]
            result.append(TaskCluster(
                label=label,
                count=len(eps),
                success_rate=success,
                example_tasks=examples,
                dominant_tool=dominant_tool,
            ))

        return sorted(result, key=lambda c: -c.count)

    def _build_pattern_summary(
        self,
        tool_stats: list[ToolStat],
        decision_acc: DecisionAccuracy,
        task_clusters: list[TaskCluster],
        episodes: list[dict],
    ) -> dict[str, Any]:
        """Build a compact JSON summary to feed to the AI."""
        failing_tools = [s for s in tool_stats if s.failure_rate > 0.05]
        struggling_clusters = [c for c in task_clusters if c.success_rate < 0.7 and c.count >= 3]
        strong_clusters = [c for c in task_clusters if c.success_rate >= 0.9 and c.count >= 5]

        # Find what task types appear just before failures
        failure_contexts: list[str] = []
        for ep in episodes:
            if ep.get("outcome") == "incorrect":
                failure_contexts.append(ep.get("task", "")[:80])

        # Enrich warning value
        enrich_value = decision_acc.enrich_saved_something
        proceed_safe = decision_acc.proceed_was_safe
        enrich_episodes = decision_acc.enrich_then_correct + decision_acc.enrich_then_incorrect
        proceed_episodes = decision_acc.proceed_then_correct + decision_acc.proceed_then_incorrect

        return {
            "total_episodes": len(episodes),
            "tool_failure_rates": {
                s.tool: {"failure_rate": round(s.failure_rate, 3), "n": s.total}
                for s in failing_tools
            },
            "struggling_workflows": [
                {"label": c.label, "success_rate": round(c.success_rate, 3), "n": c.count}
                for c in struggling_clusters
            ],
            "strong_workflows": [
                {"label": c.label, "success_rate": round(c.success_rate, 3), "n": c.count}
                for c in strong_clusters
            ],
            "enrich_decision_accuracy": {
                "value": round(enrich_value, 3),
                "n": enrich_episodes,
                "interpretation": (
                    "Sentigent's caution is mostly useful" if enrich_value > 0.7
                    else "Sentigent is being overly cautious" if enrich_value < 0.5 and enrich_episodes > 10
                    else "mixed"
                ),
            },
            "proceed_safety": {
                "value": round(proceed_safe, 3),
                "n": proceed_episodes,
            },
            "recent_failures": failure_contexts[:10],
            "most_used_tools": [
                {"tool": s.tool, "n": s.total}
                for s in sorted(tool_stats, key=lambda x: -x.total)[:5]
            ],
        }

    # ── AI synthesis ──────────────────────────────────────────────────────────

    def _ai_synthesize(self, pattern_data: dict[str, Any]) -> tuple[list[str], str]:
        """Call Claude Haiku to generate natural language suggestions."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        # Try loading from sentigent .env if not in environment
        if not api_key:
            env_candidates = [
                Path(__file__).parent.parent.parent / ".env",  # project root
                Path.home() / ".claude" / ".env",
                Path(".env"),
            ]
            for env_path in env_candidates:
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if line.startswith("ANTHROPIC_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip("\"'")
                            break
                if api_key:
                    break
        if not api_key:
            return self._fallback_suggestions(pattern_data), self._fallback_summary(pattern_data)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            prompt = f"""You are an expert at analyzing AI coding agent behavior patterns.
Below is a statistical summary of how an AI agent (Claude Code with Sentigent judgment layer) has been performing.

PATTERN DATA:
{json.dumps(pattern_data, indent=2)}

Your task: Generate exactly 4 specific, actionable suggestions for how the USER should change how they interact with their AI agent to get better results.

Rules:
- Focus on HOW the user phrases requests and structures their workflow
- Give concrete examples (e.g. "Instead of asking to 'run tests', say 'run pytest tests/unit/ and fix any failures before proceeding'")  
- If failure rates are low or data is limited, say so honestly and give preventive suggestions
- Do NOT suggest changes to the AI system itself — only user behavior
- Keep each suggestion under 2 sentences

Then write a 1-sentence executive summary of the agent's current state.

Respond in this exact JSON format:
{{
  "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3", "suggestion 4"],
  "summary": "one sentence summary"
}}"""

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Extract JSON from response
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return parsed.get("suggestions", []), parsed.get("summary", "")
        except Exception as exc:
            err_str = str(exc)
            if "credit balance is too low" in err_str or "insufficient_quota" in err_str:
                logger.warning("Anthropic API: insufficient credits. Add credits at console.anthropic.com → Plans & Billing")
                self._ai_error = "⚠ AI suggestions unavailable: Anthropic account has no credits. Add credits at console.anthropic.com."
            else:
                logger.debug("AI synthesis failed: %s", exc)

        return self._fallback_suggestions(pattern_data), self._fallback_summary(pattern_data)

    def _fallback_suggestions(self, data: dict) -> list[str]:
        """Generate rule-based suggestions when AI is unavailable."""
        suggestions = []

        # Failing tools
        for tool, stats in data.get("tool_failure_rates", {}).items():
            if stats["failure_rate"] > 0.1:
                suggestions.append(
                    f"{tool} has a {stats['failure_rate']:.0%} failure rate. "
                    f"Try specifying exact paths and avoiding shell-specific syntax when asking for {tool} operations."
                )

        # Struggling workflows
        for wf in data.get("struggling_workflows", []):
            suggestions.append(
                f"'{wf['label']}' only succeeds {wf['success_rate']:.0%} of the time. "
                f"Break these tasks into smaller steps and verify each step before proceeding."
            )

        # Enrich over-caution
        enrich = data.get("enrich_decision_accuracy", {})
        if enrich.get("interpretation") == "Sentigent is being overly cautious" and enrich.get("n", 0) > 10:
            suggestions.append(
                "Sentigent is flagging many actions for review but they succeed anyway. "
                "Consider adjusting the profile threshold or being more explicit about your intent in prompts."
            )

        if not suggestions:
            suggestions.append(
                f"Agent is performing well across {data.get('total_episodes', 0)} operations. "
                "Keep providing clear task context and explicit success criteria."
            )

        return suggestions[:4]

    def _fallback_summary(self, data: dict) -> str:
        total = data.get("total_episodes", 0)
        failing = data.get("tool_failure_rates", {})
        if not failing:
            return f"Agent is operating cleanly across {total} observed actions with no significant failure patterns."
        worst = max(failing.items(), key=lambda x: x[1]["failure_rate"])
        return (
            f"Agent has completed {total} actions; primary concern is {worst[0]} "
            f"with {worst[1]['failure_rate']:.0%} failure rate."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_tool(self, ep: dict) -> str:
        try:
            ctx = ep.get("context", {})
            if isinstance(ctx, str):
                ctx = json.loads(ctx)
            tool = ctx.get("tool_name", "")
            if tool:
                return tool
        except Exception:
            pass
        task = ep.get("task", "")
        if ":" in task:
            return task.split(":")[0].strip()
        return "unknown"

    def _empty_report(self, lookback_days: int, reason: str = "") -> CoachingReport:
        return CoachingReport(
            agent_id=self.agent_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            lookback_days=lookback_days,
            tool_stats=[],
            decision_accuracy=DecisionAccuracy(),
            task_clusters=[],
            suggestions=[reason or "Not enough data yet. Keep using the agent to build up pattern history."],
            summary="Insufficient data for analysis.",
        )
