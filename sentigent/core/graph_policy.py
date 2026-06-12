"""Phase 6B: Graph-Based Policy Engine.

Policies expressed as graph queries on the org relationship graph (org_relationships),
rather than flat regex patterns. Enables policies that compose naturally.

Example — instead of a fragile regex for "payment files":

    # Flat (today):
    {"trigger_pattern": "payment", "enforce_action": "escalate"}

    # Graph policy (Phase 6):
    {
        "name": "payment-critical-files",
        "match_entity_type": "file",
        "match_tag": "payment-critical",
        "relationship": "TAGGED",
        "enforce_action": "escalate",
        "reason": "Payment-critical file requires human review",
    }

The engine checks: does any file/service in the action's scope appear in the
org_relationships graph under a matching relationship + tag?

Graph policies are stored in a local SQLite table (graph_policies) so they work
offline and without Supabase, with optional sync.

30+ flat rules with complex interactions → graph traversals that compose cleanly.

Usage::

    from sentigent.core.graph_policy import GraphPolicyEngine, GraphPolicy

    engine = GraphPolicyEngine(db_path, org_id)
    engine.add_policy(GraphPolicy(
        name="payment-critical",
        match_entity_type="file",
        match_relationship="TAGGED",
        match_tag="payment-critical",
        enforce_action="escalate",
        enforce_reason="Payment-critical file touched — human review required",
        severity="critical",
    ))

    result = engine.evaluate(
        files_touched=["payments/processor.py"],
        task="add retry logic",
    )
    # result.action → "escalate"
    # result.reason → "Payment-critical file touched..."
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sentigent.graph_policy")


@dataclass
class GraphPolicy:
    """A single graph-based policy rule."""

    name: str
    description: str = ""

    # Graph match conditions (all must match)
    match_entity_type: str = ""     # "file" | "service" | "database" | "" (any)
    match_relationship: str = ""    # e.g. "TAGGED", "DEPENDS_ON", "OWNED_BY", "" (any)
    match_tag: str = ""             # value of the 'to_entity' when relationship=TAGGED
    match_to_type: str = ""         # restrict to_entity type
    match_task_pattern: str = ""    # optional regex on the task description

    # Action
    enforce_action: str = "slow_down"  # escalate | slow_down | enrich | block
    enforce_reason: str = ""
    severity: str = "medium"           # low | medium | high | critical
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "match_entity_type": self.match_entity_type,
            "match_relationship": self.match_relationship,
            "match_tag": self.match_tag,
            "match_to_type": self.match_to_type,
            "match_task_pattern": self.match_task_pattern,
            "enforce_action": self.enforce_action,
            "enforce_reason": self.enforce_reason,
            "severity": self.severity,
            "is_active": self.is_active,
        }


@dataclass
class GraphPolicyMatch:
    """Result of a graph policy evaluation."""

    policy_name: str
    action: str
    reason: str
    severity: str
    matched_entity: str    # the entity in the action that triggered the policy
    matched_relationship: str


class GraphPolicyEngine:
    """Evaluate graph-based policies against org relationship graph.

    Falls back gracefully when org_relationships table doesn't exist or Supabase
    is unavailable — returns None (no match) in that case.
    """

    def __init__(self, db_path: str, org_id: str) -> None:
        self.db_path = db_path
        self.org_id = org_id
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create graph_policies table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                match_entity_type TEXT DEFAULT '',
                match_relationship TEXT DEFAULT '',
                match_tag TEXT DEFAULT '',
                match_to_type TEXT DEFAULT '',
                match_task_pattern TEXT DEFAULT '',
                enforce_action TEXT NOT NULL DEFAULT 'slow_down',
                enforce_reason TEXT DEFAULT '',
                severity TEXT DEFAULT 'medium',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(org_id, name)
            )
        """)
        conn.commit()
        conn.close()

    def add_policy(self, policy: GraphPolicy) -> bool:
        """Add or update a graph policy. Returns True on success."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_policies
                (org_id, name, description, match_entity_type, match_relationship,
                 match_tag, match_to_type, match_task_pattern, enforce_action,
                 enforce_reason, severity, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.org_id,
                    policy.name,
                    policy.description,
                    policy.match_entity_type,
                    policy.match_relationship,
                    policy.match_tag,
                    policy.match_to_type,
                    policy.match_task_pattern,
                    policy.enforce_action,
                    policy.enforce_reason,
                    policy.severity,
                    1 if policy.is_active else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as exc:
            logger.debug("graph_policy add_policy failed: %s", exc)
            return False

    def list_policies(self) -> list[GraphPolicy]:
        """Return all active policies for this org."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM graph_policies WHERE org_id = ? AND is_active = 1",
                (self.org_id,),
            ).fetchall()
            conn.close()
            return [self._row_to_policy(r) for r in rows]
        except Exception:
            return []

    def evaluate(
        self,
        files_touched: list[str],
        task: str = "",
        context: dict[str, Any] | None = None,
    ) -> GraphPolicyMatch | None:
        """Evaluate graph policies for a given action.

        Args:
            files_touched: List of files/services/entities involved in the action.
            task: Task description (for task_pattern matching).
            context: Optional context dict.

        Returns:
            GraphPolicyMatch if a policy fires, None otherwise.
            Returns highest-severity match if multiple fire.
        """
        policies = self.list_policies()
        if not policies or not files_touched:
            return None

        # Load relevant relationships from SQLite (org_relationships if available)
        relationships = self._load_relationships(files_touched)

        matches: list[GraphPolicyMatch] = []

        for policy in policies:
            # Task pattern check (if specified)
            if policy.match_task_pattern:
                try:
                    if not re.search(policy.match_task_pattern, task, re.IGNORECASE):
                        continue
                except re.error:
                    pass

            # Check each entity involved in the action
            for entity in files_touched:
                match = self._check_entity(entity, policy, relationships)
                if match:
                    matches.append(match)

        if not matches:
            return None

        # Return highest severity
        sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        matches.sort(key=lambda m: sev_order.get(m.severity, 0), reverse=True)
        return matches[0]

    @staticmethod
    def _row_to_policy(row: Any) -> GraphPolicy:
        """Convert a SQLite row to a GraphPolicy."""
        return GraphPolicy(
            name=row["name"],
            description=row["description"] or "",
            match_entity_type=row["match_entity_type"] or "",
            match_relationship=row["match_relationship"] or "",
            match_tag=row["match_tag"] or "",
            match_to_type=row["match_to_type"] or "",
            match_task_pattern=row["match_task_pattern"] or "",
            enforce_action=row["enforce_action"],
            enforce_reason=row["enforce_reason"] or "",
            severity=row["severity"],
            is_active=bool(row["is_active"]),
        )

    def _load_relationships(self, entities: list[str]) -> list[dict]:
        """Load org_relationships rows for the given entities from SQLite.

        Falls back to empty list if table doesn't exist (e.g., no org brain yet).
        """
        if not entities:
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" * len(entities))
            rows = conn.execute(
                f"""
                SELECT from_entity, from_type, relationship, to_entity, to_type, weight, metadata
                FROM org_relationships
                WHERE org_id = ?
                  AND (from_entity IN ({placeholders}) OR to_entity IN ({placeholders}))
                """,
                [self.org_id, *entities, *entities],
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _check_entity(
        self,
        entity: str,
        policy: GraphPolicy,
        relationships: list[dict],
    ) -> GraphPolicyMatch | None:
        """Check if a single entity triggers a policy via graph traversal."""

        # Direct entity-type filter
        if policy.match_entity_type:
            # Infer entity type from name heuristics if not in relationships
            inferred_type = _infer_entity_type(entity)
            if inferred_type != policy.match_entity_type and policy.match_entity_type != "*":
                # Still check via relationships
                pass

        # Check if the entity appears in matching relationships
        for rel in relationships:
            from_entity = rel.get("from_entity", "")
            to_entity = rel.get("to_entity", "")
            relationship = rel.get("relationship", "")
            from_type = rel.get("from_type", "")
            to_type = rel.get("to_type", "")

            # Entity must be the source of the relationship
            if from_entity != entity:
                continue

            # Relationship type filter
            if policy.match_relationship and relationship != policy.match_relationship:
                continue

            # Tag filter (to_entity is the tag value)
            if policy.match_tag and to_entity != policy.match_tag:
                continue

            # to_type filter
            if policy.match_to_type and to_type != policy.match_to_type:
                continue

            # Match!
            return GraphPolicyMatch(
                policy_name=policy.name,
                action=policy.enforce_action,
                reason=policy.enforce_reason or (
                    f"Graph policy '{policy.name}': {entity} "
                    f"—[{relationship}]→ {to_entity}"
                ),
                severity=policy.severity,
                matched_entity=entity,
                matched_relationship=relationship,
            )

        # Also check: entity name-matches the tag (no stored relationship needed)
        # Split compound tags like "payment-critical" into keywords ["payment", "critical"]
        # and check if any keyword appears in the entity path.
        if policy.match_tag:
            tag_keywords = [
                kw for kw in re.split(r"[-_\s]+", policy.match_tag.lower())
                if len(kw) >= 4
            ]
            entity_lower = entity.lower()
            if tag_keywords and any(kw in entity_lower for kw in tag_keywords):
                inferred_type = _infer_entity_type(entity)
                if not policy.match_entity_type or inferred_type == policy.match_entity_type:
                    return GraphPolicyMatch(
                        policy_name=policy.name,
                        action=policy.enforce_action,
                        reason=policy.enforce_reason or (
                            f"Graph policy '{policy.name}': entity '{entity}' "
                            f"matches tag '{policy.match_tag}'"
                        ),
                        severity=policy.severity,
                        matched_entity=entity,
                        matched_relationship="name-match",
                    )

        return None


def _infer_entity_type(entity: str) -> str:
    """Infer entity type from name heuristics."""
    if re.search(r"\.\w{1,6}$", entity):
        return "file"
    if re.search(r"\b(db|database|table|schema|migration)\b", entity, re.IGNORECASE):
        return "database"
    if re.search(r"\b(api|service|endpoint|server|lambda|function)\b", entity, re.IGNORECASE):
        return "service"
    return "file"  # default
