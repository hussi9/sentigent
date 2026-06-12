"""Phase 3: Context Assembly — domain-aware context routing.

Replaces the generic world model keyword dump with intelligent,
domain-classified context packs that surface the right org knowledge
for each evaluation.

Domain → Context Pack:
  deploy   → critical_entities, deployment_procedures, blast_radius (relationships)
  auth     → security_practices, member_approvers, critical_entities
  data     → vocabulary, critical_entities, data_owners (relationships)
  finance  → security_practices, member_approvers, vocabulary
  comms    → vocabulary, member_context
  general  → all layers, lower top_k

Usage::

    from sentigent.core.context_assembler import ContextAssembler, classify_domain

    domain = classify_domain(task, tool_name)
    ctx = assembler.assemble(
        task=task,
        tool_name=tool_name,
        domain=domain,
        agent_id=agent_id,
        task_context={"_task_goal": goal, "_task_scope": scope},
    )
    # ctx is a dict ready to merge into the evaluation context
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Domain keywords ──────────────────────────────────────────────────────────

_DEPLOY_KEYWORDS = frozenset({
    "deploy", "release", "rollout", "terraform", "helm", "k8s", "kubernetes",
    "docker", "compose", "lambda", "ecs", "gke", "aks", "eks", "ci", "cd",
    "pipeline", "artifact", "image", "push", "publish", "ship", "environment",
    "staging", "production", "prod", "infra", "infrastructure", "ansible",
})
_AUTH_KEYWORDS = frozenset({
    "auth", "authentication", "authorization", "oauth", "jwt", "token", "saml",
    "sso", "ldap", "password", "credential", "secret", "key", "permission",
    "rbac", "role", "session", "login", "logout", "signup", "user", "identity",
    "mfa", "2fa", "totp", "cookie", "csrf",
})
_DATA_KEYWORDS = frozenset({
    "database", "db", "postgres", "mysql", "mongo", "redis", "migration",
    "schema", "table", "index", "query", "sql", "nosql", "etl", "pipeline",
    "data", "dataset", "s3", "storage", "backup", "restore", "dump",
    "transaction", "rollback", "commit", "alter", "drop", "truncate",
})
_FINANCE_KEYWORDS = frozenset({
    "payment", "billing", "invoice", "refund", "charge", "stripe", "paypal",
    "bank", "transaction", "money", "price", "cost", "revenue", "tax",
    "vat", "gst", "pci", "card", "account", "ledger", "audit",
})
_COMMS_KEYWORDS = frozenset({
    "email", "slack", "notify", "notification", "webhook", "sms", "twilio",
    "sendgrid", "mailchimp", "message", "broadcast", "alert", "pagerduty",
    "opsgenie", "zendesk", "intercom", "support", "ticket",
})

# Tool name → domain hints
_TOOL_DOMAIN_HINTS: dict[str, str] = {
    "terraform": "deploy",
    "kubectl": "deploy",
    "docker": "deploy",
    "ansible": "deploy",
    "pg_dump": "data",
    "psql": "data",
    "mysql": "data",
}


def classify_domain(task: str, tool_name: str = "") -> str:
    """Classify the evaluation domain from task description + tool name.

    Returns one of: "deploy" | "auth" | "data" | "finance" | "comms" | "general"

    Uses a simple keyword vote with tool-name hints. Fast — no I/O.
    """
    combined = (task + " " + tool_name).lower()
    words = set(re.findall(r"\w+", combined))

    # Tool-name direct hit
    tool_lower = tool_name.lower()
    for tool_prefix, domain in _TOOL_DOMAIN_HINTS.items():
        if tool_prefix in tool_lower:
            return domain

    # Keyword vote
    scores: dict[str, int] = {
        "deploy": len(words & _DEPLOY_KEYWORDS),
        "auth": len(words & _AUTH_KEYWORDS),
        "data": len(words & _DATA_KEYWORDS),
        "finance": len(words & _FINANCE_KEYWORDS),
        "comms": len(words & _COMMS_KEYWORDS),
    }
    best_domain, best_score = max(scores.items(), key=lambda kv: kv[1])
    return best_domain if best_score > 0 else "general"


# ── Context packs ─────────────────────────────────────────────────────────────
# Each pack controls how many items to pull from each knowledge layer,
# and which layers to surface directly (vs. as background context).

@dataclass
class ContextPack:
    """Configuration for what org knowledge to surface for a domain."""
    top_k_vocab: int = 5
    top_k_entities: int = 4
    security_priority: bool = False    # elevate security practices to foreground
    member_context: bool = True        # include member context
    relationship_types: list[str] = field(default_factory=list)  # entity relationship types
    # boost: if True, sets consequence_severity to at least 0.8 if critical entities found
    boost_critical_entities: bool = True


CONTEXT_PACKS: dict[str, ContextPack] = {
    "deploy": ContextPack(
        top_k_vocab=4,
        top_k_entities=8,
        security_priority=False,
        member_context=True,
        relationship_types=["DEPENDS_ON", "DEPLOYED_WITH", "OWNED_BY"],
        boost_critical_entities=True,
    ),
    "auth": ContextPack(
        top_k_vocab=4,
        top_k_entities=6,
        security_priority=True,
        member_context=True,
        relationship_types=["OWNED_BY", "APPROVES", "REVIEWS"],
        boost_critical_entities=True,
    ),
    "data": ContextPack(
        top_k_vocab=8,
        top_k_entities=8,
        security_priority=False,
        member_context=True,
        relationship_types=["DEPENDS_ON", "REFERENCED_BY", "OWNED_BY"],
        boost_critical_entities=True,
    ),
    "finance": ContextPack(
        top_k_vocab=6,
        top_k_entities=6,
        security_priority=True,
        member_context=True,
        relationship_types=["OWNED_BY", "APPROVES"],
        boost_critical_entities=True,
    ),
    "comms": ContextPack(
        top_k_vocab=8,
        top_k_entities=4,
        security_priority=False,
        member_context=True,
        relationship_types=[],
        boost_critical_entities=False,
    ),
    "general": ContextPack(
        top_k_vocab=5,
        top_k_entities=5,
        security_priority=False,
        member_context=True,
        relationship_types=[],
        boost_critical_entities=True,
    ),
}


# ── ContextAssembler ─────────────────────────────────────────────────────────

class ContextAssembler:
    """Assembles domain-aware evaluation context from org knowledge layers.

    Replaces the generic world model dump in engine.py Step 0b.
    Always fails open — any error returns an empty dict.
    """

    def __init__(self, supabase_client: Any, org_id: str) -> None:
        self._client = supabase_client
        self._org_id = org_id

    def assemble(
        self,
        task: str,
        tool_name: str,
        domain: str,
        agent_id: str = "",
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a domain-aware context dict for injection into evaluate().

        Args:
            task: The evaluation task description
            tool_name: The tool being evaluated
            domain: Classified domain ("deploy", "auth", etc.)
            agent_id: Agent identifier for member context
            task_context: Existing task context (goal, scope, constraints from Phase 2)

        Returns:
            Dict with keys:
              _org_world_model       → full org context dict (backward compat)
              _domain                → classified domain
              _critical_entities_in_task → list of critical entity names
              consequence_severity   → boosted if critical entities in scope
              _relationships         → list of entity relationship dicts
        """
        try:
            from sentigent.memory.world_model import WorldModelQuery
            query = WorldModelQuery(self._client, self._org_id)
            pack = CONTEXT_PACKS.get(domain, CONTEXT_PACKS["general"])

            task_lower = (task + " " + tool_name).lower()

            # Augment task text with task_context goal for richer keyword matching
            if task_context:
                goal = task_context.get("_task_goal", "")
                if goal:
                    task_lower = (task_lower + " " + goal).lower()

            org_ctx = query.get_context(
                task=task,
                tool_name=tool_name,
                agent_id=agent_id if pack.member_context else "",
                top_k_vocab=pack.top_k_vocab,
                top_k_entities=pack.top_k_entities,
                security_priority=pack.security_priority,
            )

            result: dict[str, Any] = {
                "_org_world_model": org_ctx.to_dict(),
                "_domain": domain,
            }

            # Surface critical entities
            critical_entities = [
                e["name"] for e in org_ctx.to_dict().get("relevant_entities", [])
                if e.get("criticality") == "critical"
            ]
            if critical_entities:
                result["_critical_entities_in_task"] = critical_entities
                if pack.boost_critical_entities:
                    # Injected as a hint — engine will take max with existing severity
                    result["_critical_entity_severity_hint"] = 0.8

            # Pull entity relationships for this domain
            if pack.relationship_types:
                rels = self._get_relationships(
                    task_lower=task_lower,
                    relationship_types=pack.relationship_types,
                )
                if rels:
                    result["_relationships"] = rels

            return result

        except Exception as exc:
            logger.debug("context_assembler.assemble failed: %s", exc)
            return {}

    def _get_relationships(
        self,
        task_lower: str,
        relationship_types: list[str],
    ) -> list[dict[str, Any]]:
        """Query org_relationships for entities mentioned in the task.

        Returns list of relationship dicts: {from, relationship, to, weight, metadata}
        """
        try:
            resp = (
                self._client.table("org_relationships")
                .select("from_entity,from_type,relationship,to_entity,to_type,weight,metadata")
                .eq("org_id", self._org_id)
                .in_("relationship", relationship_types)
                .limit(50)
                .execute()
            )
            rows = resp.data or []
            # Filter to rows where from_entity or to_entity appears in task text
            relevant = [
                r for r in rows
                if r["from_entity"].lower() in task_lower
                or r["to_entity"].lower() in task_lower
            ]
            return relevant[:12]  # cap for context size
        except Exception as exc:
            logger.debug("relationships query failed: %s", exc)
            return []

    def add_relationship(
        self,
        from_entity: str,
        from_type: str,
        relationship: str,
        to_entity: str,
        to_type: str,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Upsert a relationship into org_relationships.

        Returns True on success, False on error.
        """
        try:
            self._client.table("org_relationships").upsert({
                "org_id": self._org_id,
                "from_entity": from_entity,
                "from_type": from_type,
                "relationship": relationship,
                "to_entity": to_entity,
                "to_type": to_type,
                "weight": weight,
                "metadata": metadata or {},
            }, on_conflict="org_id,from_entity,relationship,to_entity").execute()
            return True
        except Exception as exc:
            logger.warning("add_relationship failed: %s", exc)
            return False
