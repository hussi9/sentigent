"""Org World Model — Layer 2 organizational knowledge extraction and query.

The world model answers the question: "What does this org know about itself?"

It captures three things from all agent activity in the org:
  1. Vocabulary — org-specific lingo extracted from tasks and conversations
  2. Security practices — stances inferred from what gets blocked/escalated
  3. Domain entities — services, databases, teams with criticality scores
  4. Member contexts — per-person style, expertise, risk tolerance

Before every judgment, the engine calls `get_context()` which returns a
structured context object enriching the evaluation with org-specific knowledge.

Without world model: "Deploy the auth service" → moderate caution.
With world model:    "Deploy the auth service" →
    org says deploy = staging first,
    auth-service = critical entity,
    3 recent escalations for auth deploys,
    member Sarah = conservative risk tolerance
    → ESCALATE.

Sources observed:
  - Synced episodes (task descriptions, tool inputs, decisions, outcomes)
  - Policy violations (what the org considers risky)
  - Individual interaction patterns (per-person)
  - Manual curation via dashboard
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sentigent.world_model")


# ─── Domain vocabulary ───────────────────────────────────────────────────────

# Terms that signal deployment context
DEPLOY_SIGNALS = {"deploy", "ship", "release", "push", "publish", "rollout", "launch", "promote"}
# Terms that signal database context
DB_SIGNALS = {"database", "db", "postgres", "mysql", "sqlite", "migration", "schema", "table",
              "query", "sql", "drop", "truncate", "seed"}
# Terms that signal auth/security context
AUTH_SIGNALS = {"auth", "authentication", "token", "jwt", "oauth", "credential", "secret",
                "password", "key", "permission", "role", "access"}
# Terms that signal infrastructure
INFRA_SIGNALS = {"kubernetes", "k8s", "docker", "container", "pod", "service", "ingress",
                 "terraform", "aws", "gcp", "azure", "s3", "lambda", "ec2"}
# Terms that signal payment/financial context
PAYMENT_SIGNALS = {"payment", "billing", "invoice", "charge", "refund", "stripe", "transaction",
                   "revenue", "subscription", "checkout"}

CATEGORY_SIGNALS = {
    "deployment": DEPLOY_SIGNALS,
    "database": DB_SIGNALS,
    "security": AUTH_SIGNALS,
    "infrastructure": INFRA_SIGNALS,
    "payments": PAYMENT_SIGNALS,
}

# Entity type detection patterns
ENTITY_PATTERNS = {
    "service": re.compile(
        r'\b(\w+[-_]?(?:service|svc|api|server|worker|job|scheduler|proxy|gateway))\b', re.I
    ),
    "database": re.compile(
        r'\b(\w+[-_]?(?:db|database|store|cache|redis|postgres|mysql|mongo))\b', re.I
    ),
    "team": re.compile(
        r'\b(?:team[-_]?\w+|\w+[-_]?team|squad[-_]?\w+|\w+[-_]?squad)\b', re.I
    ),
}


# ─── Data types ──────────────────────────────────────────────────────────────

@dataclass
class VocabTerm:
    term: str
    definition: str | None
    category: str
    confidence: float
    occurrences: int
    examples: list[str]


@dataclass
class SecurityPractice:
    practice_type: str   # 'required' | 'forbidden' | 'escalate' | 'prefer' | 'avoid'
    description: str
    applies_to: str | None
    confidence: float
    evidence_count: int


@dataclass
class WorldEntity:
    entity_type: str     # 'service' | 'database' | 'team' | 'system' | 'concept' | 'api'
    entity_name: str
    criticality: str     # 'critical' | 'high' | 'medium' | 'low'
    mention_count: int
    escalation_count: int
    aliases: list[str]


@dataclass
class MemberContext:
    member_identifier: str
    member_type: str     # 'human' | 'agent'
    domains: list[str]
    communication_style: str
    risk_tolerance: str
    typical_tools: list[str]
    escalation_rate: float
    accuracy_rate: float
    interaction_count: int


@dataclass
class OrgContext:
    """Enriched context injected into every evaluation."""
    org_id: str
    vocabulary: list[VocabTerm] = field(default_factory=list)
    security_practices: list[SecurityPractice] = field(default_factory=list)
    relevant_entities: list[WorldEntity] = field(default_factory=list)
    member_context: MemberContext | None = None

    def to_prompt_fragment(self) -> str:
        """Serialize to a compact string for LLM prompt injection."""
        parts: list[str] = []

        if self.vocabulary:
            vocab_lines = []
            for v in self.vocabulary[:8]:  # top 8 by relevance
                defn = f": {v.definition}" if v.definition else ""
                vocab_lines.append(f"  - {v.term}{defn} [{v.category}]")
            parts.append("Org vocabulary:\n" + "\n".join(vocab_lines))

        if self.security_practices:
            sec_lines = [f"  - [{p.practice_type.upper()}] {p.description}"
                         for p in self.security_practices[:6]]
            parts.append("Security practices in this org:\n" + "\n".join(sec_lines))

        if self.relevant_entities:
            ent_lines = [
                f"  - {e.entity_name} ({e.entity_type}, criticality={e.criticality},"
                f" mentions={e.mention_count}, escalations={e.escalation_count})"
                for e in self.relevant_entities[:6]
            ]
            parts.append("Relevant entities:\n" + "\n".join(ent_lines))

        if self.member_context:
            mc = self.member_context
            parts.append(
                f"Member context: {mc.member_identifier} | style={mc.communication_style} |"
                f" risk={mc.risk_tolerance} | domains={','.join(mc.domains[:4])} |"
                f" escalation_rate={mc.escalation_rate:.1%} | accuracy={mc.accuracy_rate:.1%}"
            )

        return "\n\n".join(parts) if parts else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "vocabulary": [
                {"term": v.term, "definition": v.definition,
                 "category": v.category, "confidence": v.confidence}
                for v in self.vocabulary
            ],
            "security_practices": [
                {"type": p.practice_type, "description": p.description,
                 "applies_to": p.applies_to, "confidence": p.confidence}
                for p in self.security_practices
            ],
            "relevant_entities": [
                {"name": e.entity_name, "type": e.entity_type,
                 "criticality": e.criticality, "mentions": e.mention_count,
                 "escalations": e.escalation_count}
                for e in self.relevant_entities
            ],
            "member_context": {
                "identifier": self.member_context.member_identifier,
                "type": self.member_context.member_type,
                "domains": self.member_context.domains,
                "style": self.member_context.communication_style,
                "risk_tolerance": self.member_context.risk_tolerance,
                "escalation_rate": self.member_context.escalation_rate,
                "accuracy_rate": self.member_context.accuracy_rate,
            } if self.member_context else None,
        }


# ─── Extraction helpers ───────────────────────────────────────────────────────

def _extract_terms(text: str) -> list[str]:
    """Extract candidate terms from text: multi-word technical phrases + single tokens."""
    text = text.lower()
    tokens = re.findall(r'\b[a-z][a-z0-9_-]*[a-z0-9]\b', text)

    candidates = []
    # 2–3 word phrases (e.g. "auth service", "staging environment")
    words = text.split()
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i+1]}"
        if 4 <= len(bigram) <= 40:
            candidates.append(bigram)
    for i in range(len(words) - 2):
        trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
        if 6 <= len(trigram) <= 50:
            candidates.append(trigram)

    # Single meaningful tokens (4+ chars, not generic stop words)
    stop = {"the", "for", "and", "with", "this", "that", "from", "have", "been",
            "are", "was", "will", "not", "but", "can", "its", "into", "task",
            "tool", "file", "code", "test", "make", "also", "some", "than",
            "then", "when", "where", "which", "while", "about", "after",
            "before", "there", "their", "these", "those", "each"}
    for t in tokens:
        if len(t) >= 4 and t not in stop:
            candidates.append(t)

    return list(dict.fromkeys(candidates))  # deduplicate preserving order


def _categorize_term(term: str) -> str:
    """Assign a category to a term based on domain signals."""
    t = term.lower()
    for category, signals in CATEGORY_SIGNALS.items():
        if any(s in t for s in signals):
            return category
    return "general"


def _extract_entities(text: str) -> list[tuple[str, str]]:
    """Return (entity_name, entity_type) pairs from text."""
    results = []
    for entity_type, pattern in ENTITY_PATTERNS.items():
        for match in pattern.finditer(text):
            name = match.group(0).lower().strip("-_")
            if len(name) >= 4:
                results.append((name, entity_type))
    return results


def _infer_criticality(entity_name: str, mention_count: int, escalation_count: int) -> str:
    """Infer criticality from name signals and observed escalation rate."""
    name = entity_name.lower()
    # Name-based critical signals
    if any(s in name for s in {"auth", "payment", "billing", "prod", "production",
                                "security", "secret", "credential", "main", "master"}):
        return "critical"
    if any(s in name for s in {"staging", "gateway", "api", "database", "db",
                                "admin", "deploy", "release"}):
        base = "high"
    else:
        base = "medium"

    # Escalation rate override
    if mention_count > 0:
        esc_rate = escalation_count / mention_count
        if esc_rate >= 0.3:
            return "critical"
        if esc_rate >= 0.15:
            return "high"

    return base


def _extract_communication_style(texts: list[str]) -> str:
    """Infer communication style from sample of user texts."""
    if not texts:
        return "unknown"
    avg_len = sum(len(t.split()) for t in texts) / len(texts)
    tech_terms = sum(1 for t in texts
                     for w in t.lower().split()
                     if w in {"deploy", "migrate", "schema", "api", "endpoint",
                               "auth", "token", "service", "pod", "container"})
    tech_density = tech_terms / max(len(texts), 1)
    if avg_len < 6:
        return "terse"
    if tech_density > 2:
        return "technical"
    if avg_len > 20:
        return "verbose"
    return "standard"


def _infer_risk_tolerance(escalation_rate: float, override_rate: float) -> str:
    """Infer risk tolerance from escalation and override patterns."""
    if escalation_rate > 0.3 or override_rate < 0.1:
        return "conservative"
    if escalation_rate < 0.05 and override_rate > 0.5:
        return "aggressive"
    return "medium"


# ─── WorldModelBuilder ────────────────────────────────────────────────────────

class WorldModelBuilder:
    """Extracts org knowledge from synced episodes and policy interactions.

    Called by the sync manager after each batch of episodes is written to
    Supabase. Reads synced_episodes + policy_violations, extracts vocabulary,
    security practices, entities, and member contexts, then upserts them.

    Usage:
        builder = WorldModelBuilder(supabase_client, org_id)
        builder.process_episodes(episodes)
        builder.process_policy_violations(violations)
        builder.flush()  # writes all accumulated extractions to Supabase
    """

    def __init__(self, client: Any, org_id: str) -> None:
        self._client = client
        self._org_id = org_id
        # Accumulators (term → {count, examples, category})
        self._vocab: dict[str, dict[str, Any]] = {}
        self._security: list[dict[str, Any]] = []
        self._entities: dict[str, dict[str, Any]] = {}
        self._members: dict[str, dict[str, Any]] = {}

    def process_episodes(self, episodes: list[dict[str, Any]]) -> None:
        """Extract knowledge from a batch of synced episodes."""
        for ep in episodes:
            task = ep.get("task", "")
            context = ep.get("context", {})
            decision = ep.get("decision", "")
            outcome = ep.get("outcome")
            agent_id = ep.get("agent_id", "")

            # Vocabulary extraction from task text
            self._extract_vocab_from_text(task)
            if isinstance(context, dict):
                for v in context.values():
                    if isinstance(v, str):
                        self._extract_vocab_from_text(v)

            # Entity extraction
            all_text = task + " " + json.dumps(context)
            self._extract_entities_from_text(all_text, decision, outcome)

            # Member context (from agent_id as proxy for individual)
            if agent_id:
                self._update_member(
                    identifier=agent_id,
                    member_type="agent",
                    text=task,
                    decision=decision,
                    outcome=outcome,
                    tool=context.get("tool_name", ""),
                )

    def process_policy_violations(self, violations: list[dict[str, Any]]) -> None:
        """Extract security practices from policy violation records."""
        for v in violations:
            action = v.get("action", "")
            policy_id = v.get("policy_id", "")
            context = v.get("context", {})
            tool = context.get("tool_name", "") if isinstance(context, dict) else ""
            task = v.get("task", "")

            # Map violation action to practice type
            practice_type_map = {
                "escalate": "escalate",
                "slow_down": "prefer",
                "enrich": "required",
                "block": "forbidden",
            }
            practice_type = practice_type_map.get(action, "prefer")

            # Determine what this practice applies to
            applies_to = _categorize_term(task + " " + tool)

            # Generate a description from the violation
            description = self._describe_security_practice(
                practice_type, policy_id, tool, task
            )
            if description:
                self._security.append({
                    "practice_type": practice_type,
                    "description": description,
                    "applies_to": applies_to,
                    "policy_id": policy_id,
                })

    def process_conversation(
        self,
        member_identifier: str,
        member_type: str,
        text: str,
        tool_used: str = "",
        outcome: str | None = None,
        was_escalated: bool = False,
    ) -> None:
        """Extract knowledge from a single human–agent interaction."""
        self._extract_vocab_from_text(text)
        entities = _extract_entities(text)
        for name, etype in entities:
            if name not in self._entities:
                self._entities[name] = {
                    "entity_type": etype, "mention_count": 0,
                    "escalation_count": 0, "aliases": [],
                }
            self._entities[name]["mention_count"] += 1
            if was_escalated:
                self._entities[name]["escalation_count"] += 1

        self._update_member(
            identifier=member_identifier,
            member_type=member_type,
            text=text,
            decision="",
            outcome=outcome,
            tool=tool_used,
            was_escalated=was_escalated,
        )

    def flush(self) -> dict[str, int]:
        """Write all accumulated extractions to Supabase. Returns counts."""
        counts = {
            "vocabulary": self._flush_vocabulary(),
            "security": self._flush_security(),
            "entities": self._flush_entities(),
            "members": self._flush_members(),
        }
        logger.info("World model flush: %s", counts)
        return counts

    # ── private extraction methods ───────────────────────────────────────────

    def _extract_vocab_from_text(self, text: str) -> None:
        terms = _extract_terms(text)
        for term in terms:
            if term not in self._vocab:
                self._vocab[term] = {
                    "count": 0, "examples": [], "category": _categorize_term(term)
                }
            self._vocab[term]["count"] += 1
            if len(self._vocab[term]["examples"]) < 5 and len(text) < 200:
                self._vocab[term]["examples"].append(text[:120])

    def _extract_entities_from_text(
        self, text: str, decision: str, outcome: str | None
    ) -> None:
        entities = _extract_entities(text)
        was_escalated = decision == "escalate"
        for name, etype in entities:
            if name not in self._entities:
                self._entities[name] = {
                    "entity_type": etype, "mention_count": 0,
                    "escalation_count": 0, "aliases": [],
                }
            self._entities[name]["mention_count"] += 1
            if was_escalated:
                self._entities[name]["escalation_count"] += 1

    def _update_member(
        self,
        identifier: str,
        member_type: str,
        text: str,
        decision: str,
        outcome: str | None,
        tool: str,
        was_escalated: bool = False,
    ) -> None:
        if identifier not in self._members:
            self._members[identifier] = {
                "member_type": member_type,
                "texts": [],
                "tools": [],
                "interactions": 0,
                "escalations": 0,
                "correct": 0,
                "incorrect": 0,
                "domains": set(),
            }
        m = self._members[identifier]
        m["interactions"] += 1
        if text:
            m["texts"].append(text[:100])
        if tool:
            m["tools"].append(tool)
        if was_escalated or decision == "escalate":
            m["escalations"] += 1
        if outcome == "correct":
            m["correct"] += 1
        elif outcome == "incorrect":
            m["incorrect"] += 1
        # Infer domains from text
        for domain, signals in CATEGORY_SIGNALS.items():
            if any(s in text.lower() for s in signals):
                m["domains"].add(domain)

    def _describe_security_practice(
        self, practice_type: str, policy_id: str, tool: str, task: str
    ) -> str | None:
        """Generate a human-readable security practice description."""
        task_l = task.lower()
        tool_l = tool.lower()
        if "force" in task_l and "push" in task_l:
            return "Force pushing to remote branches requires explicit approval"
        if "drop" in task_l and any(d in task_l for d in {"table", "database", "db"}):
            return "Dropping database objects requires escalation"
        if any(s in task_l for s in {"secret", "credential", ".env", "password", "api_key"}):
            return "Writing to credential or secrets files is forbidden without review"
        if "deploy" in task_l and "production" in task_l:
            return "Production deployments require explicit approval"
        if "bash" in tool_l and any(s in task_l for s in {"rm -rf", "truncate", "delete all"}):
            return "Destructive shell commands are escalated for review"
        if policy_id:
            return f"Policy '{policy_id}' ({practice_type}) applied to {tool or 'agent'} actions"
        return None

    # ── private flush methods ─────────────────────────────────────────────────

    def _flush_vocabulary(self) -> int:
        """Upsert vocabulary terms to Supabase. Returns count written."""
        # Filter: only terms seen ≥2 times, or high-signal category terms
        terms_to_write = [
            (term, data) for term, data in self._vocab.items()
            if data["count"] >= 2 or data["category"] != "general"
        ]
        if not terms_to_write:
            return 0

        # Compute confidence: log-scale, capped at 0.95
        import math
        rows = []
        for term, data in terms_to_write:
            conf = min(0.95, 0.3 + 0.1 * math.log1p(data["count"]))
            rows.append({
                "org_id": self._org_id,
                "term": term,
                "category": data["category"],
                "confidence": conf,
                "occurrence_count": data["count"],
                "examples": data["examples"][:5],
                "source": "observed",
            })

        try:
            self._client.table("org_vocabulary").upsert(
                rows,
                on_conflict="org_id,term",
            ).execute()
            return len(rows)
        except Exception as exc:
            logger.warning("vocab flush failed: %s", exc)
            return 0

    def _flush_security(self) -> int:
        """Insert new security practices (deduplicate by description)."""
        if not self._security:
            return 0
        rows = [
            {
                "org_id": self._org_id,
                "practice_type": p["practice_type"],
                "description": p["description"],
                "applies_to": p.get("applies_to"),
                "policy_id": p.get("policy_id"),
                "evidence_count": 1,
                "confidence": 0.6,
                "source": "observed",
            }
            for p in self._security
        ]
        try:
            # Insert, ignore duplicates on description
            self._client.table("org_security_practices").upsert(
                rows,
                on_conflict="org_id,description",
                ignore_duplicates=True,
            ).execute()
            return len(rows)
        except Exception as exc:
            logger.warning("security flush failed: %s", exc)
            return 0

    def _flush_entities(self) -> int:
        """Upsert world entities with computed criticality."""
        if not self._entities:
            return 0
        rows = []
        for name, data in self._entities.items():
            criticality = _infer_criticality(
                name, data["mention_count"], data["escalation_count"]
            )
            rows.append({
                "org_id": self._org_id,
                "entity_type": data["entity_type"],
                "entity_name": name,
                "criticality": criticality,
                "mention_count": data["mention_count"],
                "escalation_count": data["escalation_count"],
                "aliases": data.get("aliases", []),
            })
        try:
            self._client.table("org_world_entities").upsert(
                rows,
                on_conflict="org_id,entity_name",
            ).execute()
            return len(rows)
        except Exception as exc:
            logger.warning("entities flush failed: %s", exc)
            return 0

    def _flush_members(self) -> int:
        """Upsert member contexts with inferred style and risk tolerance."""
        if not self._members:
            return 0
        rows = []
        for identifier, data in self._members.items():
            interactions = data["interactions"]
            escalation_rate = data["escalations"] / max(interactions, 1)
            total_outcomes = data["correct"] + data["incorrect"]
            accuracy_rate = data["correct"] / max(total_outcomes, 1)
            style = _extract_communication_style(data["texts"])
            risk = _infer_risk_tolerance(escalation_rate, override_rate=0.5)
            # Top tools
            from collections import Counter
            tool_counts = Counter(data["tools"])
            typical_tools = [t for t, _ in tool_counts.most_common(5)]
            rows.append({
                "org_id": self._org_id,
                "member_identifier": identifier,
                "member_type": data["member_type"],
                "domains": list(data["domains"])[:8],
                "communication_style": style,
                "risk_tolerance": risk,
                "typical_tools": typical_tools,
                "escalation_rate": escalation_rate,
                "accuracy_rate": accuracy_rate,
                "interaction_count": interactions,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            })
        try:
            self._client.table("org_member_contexts").upsert(
                rows,
                on_conflict="org_id,member_identifier",
            ).execute()
            return len(rows)
        except Exception as exc:
            logger.warning("members flush failed: %s", exc)
            return 0


# ─── WorldModelQuery ──────────────────────────────────────────────────────────

class WorldModelQuery:
    """Queries the org world model to produce context for evaluations.

    Usage:
        query = WorldModelQuery(supabase_client, org_id)
        context = query.get_context(task, tool_name, agent_id)
        # context.to_prompt_fragment() → injected into LLM judge prompt
    """

    def __init__(self, client: Any, org_id: str) -> None:
        self._client = client
        self._org_id = org_id

    def get_context(
        self,
        task: str,
        tool_name: str = "",
        agent_id: str = "",
        top_k_vocab: int = 8,
        top_k_entities: int = 6,
        security_priority: bool = False,
    ) -> OrgContext:
        """Return an OrgContext enriched with relevant org knowledge.

        Args:
            task: Task description for keyword matching
            tool_name: Tool being evaluated (added to keyword set)
            agent_id: Agent identifier for member context
            top_k_vocab: Max vocabulary terms to surface
            top_k_entities: Max domain entities to surface
            security_priority: If True, fetch more security practices and sort
                               by severity first (used for auth/finance domains)
        """
        ctx = OrgContext(org_id=self._org_id)

        task_lower = (task + " " + tool_name).lower()
        ctx.vocabulary = self._get_relevant_vocab(task_lower, top_k_vocab)

        applies_to = _categorize_term(task_lower)
        ctx.security_practices = self._get_security_practices(
            applies_to, priority=security_priority
        )

        ctx.relevant_entities = self._get_relevant_entities(task_lower, top_k_entities)

        if agent_id:
            ctx.member_context = self._get_member_context(agent_id)

        return ctx

    def get_full_world_model(self) -> dict[str, Any]:
        """Return the full org world model for the dashboard."""
        try:
            vocab = (
                self._client.table("org_vocabulary")
                .select("*")
                .eq("org_id", self._org_id)
                .order("confidence", desc=True)
                .limit(200)
                .execute()
                .data
            )
            security = (
                self._client.table("org_security_practices")
                .select("*")
                .eq("org_id", self._org_id)
                .order("confidence", desc=True)
                .limit(100)
                .execute()
                .data
            )
            entities = (
                self._client.table("org_world_entities")
                .select("*")
                .eq("org_id", self._org_id)
                .order("mention_count", desc=True)
                .limit(100)
                .execute()
                .data
            )
            members = (
                self._client.table("org_member_contexts")
                .select("*")
                .eq("org_id", self._org_id)
                .order("interaction_count", desc=True)
                .limit(50)
                .execute()
                .data
            )
            return {
                "org_id": self._org_id,
                "vocabulary": vocab or [],
                "security_practices": security or [],
                "entities": entities or [],
                "members": members or [],
                "summary": {
                    "vocab_terms": len(vocab or []),
                    "security_practices": len(security or []),
                    "known_entities": len(entities or []),
                    "tracked_members": len(members or []),
                },
            }
        except Exception as exc:
            logger.warning("get_full_world_model failed: %s", exc)
            return {"org_id": self._org_id, "vocabulary": [], "security_practices": [],
                    "entities": [], "members": [], "summary": {}}

    # ── private query helpers ─────────────────────────────────────────────────

    def _get_relevant_vocab(self, task_lower: str, top_k: int) -> list[VocabTerm]:
        try:
            resp = (
                self._client.table("org_vocabulary")
                .select("term,definition,category,confidence,occurrence_count,examples")
                .eq("org_id", self._org_id)
                .gte("confidence", 0.4)
                .order("confidence", desc=True)
                .limit(100)
                .execute()
            )
            rows = resp.data or []
            # Filter to terms that appear in the current task
            relevant = [r for r in rows if r["term"].lower() in task_lower]
            # Fall back to top by confidence if none match
            if not relevant:
                relevant = rows[:top_k]
            return [
                VocabTerm(
                    term=r["term"],
                    definition=r.get("definition"),
                    category=r["category"],
                    confidence=r["confidence"],
                    occurrences=r["occurrence_count"],
                    examples=r.get("examples") or [],
                )
                for r in relevant[:top_k]
            ]
        except Exception as exc:
            logger.debug("vocab query failed: %s", exc)
            return []

    def _get_security_practices(self, applies_to: str, priority: bool = False) -> list[SecurityPractice]:
        try:
            limit = 30 if priority else 20
            resp = (
                self._client.table("org_security_practices")
                .select("practice_type,description,applies_to,confidence,evidence_count")
                .eq("org_id", self._org_id)
                .gte("confidence", 0.4)
                .order("evidence_count", desc=True)
                .limit(limit)
                .execute()
            )
            rows = resp.data or []
            # Prioritize practices matching the current applies_to context
            matching = [r for r in rows if r.get("applies_to") == applies_to]
            other = [r for r in rows if r.get("applies_to") != applies_to]
            # For priority domains (auth, finance), fetch more matching entries
            cap = 12 if priority else 8
            combined = (matching + other)[:cap]
            return [
                SecurityPractice(
                    practice_type=r["practice_type"],
                    description=r["description"],
                    applies_to=r.get("applies_to"),
                    confidence=r["confidence"],
                    evidence_count=r["evidence_count"],
                )
                for r in combined
            ]
        except Exception as exc:
            logger.debug("security query failed: %s", exc)
            return []

    def _get_relevant_entities(self, task_lower: str, top_k: int) -> list[WorldEntity]:
        try:
            resp = (
                self._client.table("org_world_entities")
                .select("entity_type,entity_name,criticality,mention_count,escalation_count,aliases")
                .eq("org_id", self._org_id)
                .order("mention_count", desc=True)
                .limit(150)
                .execute()
            )
            rows = resp.data or []
            # Match entities mentioned in the current task
            mentioned = [
                r for r in rows
                if r["entity_name"].lower() in task_lower or
                any(alias.lower() in task_lower for alias in (r.get("aliases") or []))
            ]
            # Always include critical entities even if not explicitly mentioned
            critical = [r for r in rows if r["criticality"] == "critical" and r not in mentioned]
            combined = mentioned + critical[:2]
            return [
                WorldEntity(
                    entity_type=r["entity_type"],
                    entity_name=r["entity_name"],
                    criticality=r["criticality"],
                    mention_count=r["mention_count"],
                    escalation_count=r["escalation_count"],
                    aliases=r.get("aliases") or [],
                )
                for r in combined[:top_k]
            ]
        except Exception as exc:
            logger.debug("entities query failed: %s", exc)
            return []

    def _get_member_context(self, agent_id: str) -> MemberContext | None:
        try:
            resp = (
                self._client.table("org_member_contexts")
                .select("*")
                .eq("org_id", self._org_id)
                .eq("member_identifier", agent_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                return None
            r = rows[0]
            return MemberContext(
                member_identifier=r["member_identifier"],
                member_type=r["member_type"],
                domains=r.get("domains") or [],
                communication_style=r.get("communication_style", "unknown"),
                risk_tolerance=r.get("risk_tolerance", "medium"),
                typical_tools=r.get("typical_tools") or [],
                escalation_rate=r.get("escalation_rate", 0.0),
                accuracy_rate=r.get("accuracy_rate", 0.5),
                interaction_count=r.get("interaction_count", 0),
            )
        except Exception as exc:
            logger.debug("member context query failed: %s", exc)
            return None
