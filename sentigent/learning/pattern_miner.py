"""Pattern Miner — extracts procedural rules from episodic memory.

Transforms raw episodes into learned patterns:
  "When amount > 25x median AND account_age < 60 days → escalate (94% success rate, n=47)"

This is how episodic memory (specific events) becomes procedural memory
(general rules), mimicking human skill acquisition.
"""

from __future__ import annotations

import json
from typing import Any

from sentigent.core.types import DecisionAction


class PatternMiner:
    """Extracts actionable patterns from accumulated episodic memory.

    Looks for recurring decision contexts that consistently lead to
    the same outcome, then promotes them to procedural rules.
    """

    def __init__(
        self,
        min_sample_size: int = 30,
        min_success_rate: float = 0.8,
        db_path: str | None = None,
    ) -> None:
        """
        Args:
            min_sample_size: Minimum episodes before a pattern is promoted
            min_success_rate: Minimum success rate for promotion
            db_path: Optional path to SQLite DB for get_patterns()
        """
        self.min_sample_size = min_sample_size
        self.min_success_rate = min_success_rate
        self.db_path = db_path

    def mine_patterns(
        self,
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Mine patterns from a list of episodes.

        Looks for context conditions that consistently predict outcomes.

        Args:
            episodes: List of episode dicts with context, decision, outcome

        Returns:
            List of discovered patterns
        """
        if len(episodes) < self.min_sample_size:
            return []

        patterns: list[dict[str, Any]] = []

        # Strategy 1: Decision-outcome correlation
        # Group episodes by decision type and check success rates
        decision_groups: dict[str, list[dict[str, Any]]] = {}
        for ep in episodes:
            decision = ep.get("decision", "unknown")
            if decision not in decision_groups:
                decision_groups[decision] = []
            decision_groups[decision].append(ep)

        for decision, group in decision_groups.items():
            if len(group) < self.min_sample_size:
                continue

            correct = sum(1 for ep in group if ep.get("outcome") == "correct")
            rate = correct / len(group)

            if rate >= self.min_success_rate:
                # Find common context features
                common_features = self._find_common_features(group)
                if common_features:
                    patterns.append({
                        "pattern_name": f"auto_{decision}_pattern",
                        "condition": common_features,
                        "learned_action": decision,
                        "success_rate": round(rate, 3),
                        "sample_size": len(group),
                    })

        # Strategy 2: Tool-failure patterns
        # Find tools that consistently fail and what the fix looked like
        tool_failure_patterns = self._mine_tool_failures(episodes)
        patterns.extend(tool_failure_patterns)

        # Strategy 3: Anomaly-escalation patterns
        # When high caution + escalation → correct, extract the anomaly conditions
        escalated = [
            ep for ep in episodes
            if ep.get("decision") == "escalate" and ep.get("outcome") == "correct"
        ]
        if len(escalated) >= 10:
            anomaly_conditions = self._extract_anomaly_conditions(escalated)
            if anomaly_conditions:
                patterns.append({
                    "pattern_name": "learned_escalation_pattern",
                    "condition": anomaly_conditions,
                    "learned_action": "escalate",
                    "success_rate": round(len(escalated) / max(1, len([
                        ep for ep in episodes if ep.get("decision") == "escalate"
                    ])), 3),
                    "sample_size": len(escalated),
                })

        return patterns

    def get_patterns(
        self,
        min_success_rate: float = 0.0,
        min_samples: int = 0,
        agent_id: str | None = None,
    ) -> list[Any]:
        """Load stored patterns from the SQLite procedural_rules table.

        Returns pattern objects with .pattern_name, .learned_action,
        .success_rate, .sample_size attributes.
        """
        import sqlite3
        from dataclasses import dataclass

        @dataclass
        class Pattern:
            pattern_name: str
            learned_action: str
            success_rate: float
            sample_size: int
            condition: Any = None

        if not self.db_path:
            import os
            self.db_path = os.path.expanduser("~/.sentigent/memory.db")

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM procedural_rules WHERE 1=1"
            params: list[Any] = []
            if min_success_rate > 0:
                query += " AND success_rate >= ?"
                params.append(min_success_rate)
            if min_samples > 0:
                query += " AND sample_size >= ?"
                params.append(min_samples)
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            query += " ORDER BY success_rate DESC, sample_size DESC"
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return [
                Pattern(
                    pattern_name=row["pattern_name"],
                    learned_action=row["learned_action"],
                    success_rate=row["success_rate"],
                    sample_size=row["sample_size"],
                    condition=row["condition"],
                )
                for row in rows
            ]
        except Exception:
            return []

    def _find_common_features(
        self,
        episodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Find context features common across episodes in a group."""
        if not episodes:
            return {}

        # Collect all context keys and their value ranges
        feature_values: dict[str, list[Any]] = {}
        for ep in episodes:
            context = ep.get("context", {})
            if isinstance(context, str):
                try:
                    context = json.loads(context)
                except (json.JSONDecodeError, TypeError):
                    continue
            for key, value in context.items():
                if key not in feature_values:
                    feature_values[key] = []
                feature_values[key].append(value)

        common: dict[str, Any] = {}
        for key, values in feature_values.items():
            # Only consider features present in >70% of episodes
            if len(values) < len(episodes) * 0.7:
                continue

            # For numeric values, find the range
            numeric_values = [v for v in values if isinstance(v, (int, float))]
            if len(numeric_values) >= len(episodes) * 0.7:
                common[key] = {
                    "type": "numeric_range",
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "median": sorted(numeric_values)[len(numeric_values) // 2],
                }

            # For string values, find the most common
            string_values = [v for v in values if isinstance(v, str)]
            if len(string_values) >= len(episodes) * 0.7:
                from collections import Counter
                most_common = Counter(string_values).most_common(3)
                if most_common[0][1] >= len(episodes) * 0.5:
                    common[key] = {
                        "type": "categorical",
                        "dominant_value": most_common[0][0],
                        "frequency": most_common[0][1] / len(episodes),
                    }

        return common

    def _mine_tool_failures(
        self,
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Mine tool-specific failure patterns.

        Finds cases where the same tool consistently fails and records:
        - Which tool is failing (Bash, Edit, Write)
        - What command prefix / file pattern triggers failures
        - How often it fails

        These become advisory patterns (not blocking rules) that surface
        in pre-hook as warnings before the tool is called again.
        """
        patterns: list[dict[str, Any]] = []

        # Group by tool_name + outcome
        from collections import defaultdict, Counter
        tool_failures: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for ep in episodes:
            if ep.get("outcome") != "incorrect":
                continue
            context = ep.get("context", {})
            if isinstance(context, str):
                try:
                    context = json.loads(context)
                except (json.JSONDecodeError, TypeError):
                    context = {}
            tool = context.get("tool_name", "")
            if tool:
                tool_failures[tool].append(ep)

        for tool, failed_eps in tool_failures.items():
            if len(failed_eps) < 5:  # lower threshold for failure patterns
                continue

            # Extract command prefixes for Bash
            if tool == "Bash":
                prefixes: list[str] = []
                for ep in failed_eps:
                    task = ep.get("task", "")
                    # task format: "Bash: <command>"
                    cmd = task[6:].strip() if task.startswith("Bash:") else task
                    parts = cmd.split()
                    if parts:
                        prefixes.append(parts[0])

                if prefixes:
                    top_prefixes = Counter(prefixes).most_common(3)
                    for prefix, count in top_prefixes:
                        if count >= 3:
                            from sentigent.core.bash_advisor import suggest_alternative
                            alt = suggest_alternative(prefix)
                            patterns.append({
                                "pattern_name": f"bash_failure_{prefix}",
                                "condition": {
                                    "tool_name": {"type": "categorical", "dominant_value": "Bash", "frequency": 1.0},
                                    "command_prefix": {"type": "categorical", "dominant_value": prefix, "frequency": count / len(failed_eps)},
                                },
                                "learned_action": "enrich",
                                "success_rate": 0.0,  # this is a failure pattern
                                "sample_size": count,
                                "advisory": f"Bash({prefix}) has failed {count} times. Consider: {alt.tool if alt else 'mcp__desktop-commander'}",
                            })
            else:
                # Generic tool failure pattern
                total = sum(1 for ep in episodes if json.loads(ep.get("context", "{}") if isinstance(ep.get("context"), str) else "{}").get("tool_name") == tool)
                failure_rate = len(failed_eps) / max(1, total)
                if failure_rate >= 0.3:  # >30% failure rate is significant
                    patterns.append({
                        "pattern_name": f"{tool.lower()}_failure_pattern",
                        "condition": {
                            "tool_name": {"type": "categorical", "dominant_value": tool, "frequency": 1.0},
                        },
                        "learned_action": "enrich",
                        "success_rate": round(1 - failure_rate, 3),
                        "sample_size": len(failed_eps),
                        "advisory": f"{tool} has a {failure_rate:.0%} failure rate ({len(failed_eps)} failures). Validate inputs carefully.",
                    })

        return patterns

    def _extract_anomaly_conditions(
        self,
        escalated_episodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract the anomaly conditions that led to successful escalations."""
        conditions: dict[str, Any] = {}

        # Look at signal patterns
        high_caution_count = 0
        for ep in escalated_episodes:
            signals = ep.get("signals", {})
            if isinstance(signals, str):
                try:
                    signals = json.loads(signals)
                except (json.JSONDecodeError, TypeError):
                    continue
            if signals.get("caution", 0) > 0.7:
                high_caution_count += 1

        if high_caution_count > len(escalated_episodes) * 0.8:
            conditions["caution_above"] = 0.7

        return conditions
