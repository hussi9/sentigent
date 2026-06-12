"""Org-level profile intelligence — Layer 2 profile-based agent behavior.

Org admins define profiles in Supabase (product_manager, security_engineer,
data_analyst, etc.). Profiles are assigned to agents by agent_id or by default
for the whole org. Each profile shapes how agents evaluate decisions:

- Value weights: how much this role cares about each dimension
  (e.g. product_manager cares more about user_impact than code_correctness)
- Signal thresholds: how aggressive caution/doubt signals are
- AI context hints: injected into the coach's analysis prompt
- Policy templates: auto-seeded org policies for this role

Architecture:
    Layer 1 profiles (code-level): financial_ops, code_review, customer_support
        ↓ extended by
    Layer 2 profiles (org admin via Supabase): product_manager, security_eng, etc.
        ↓ combined into
    Effective profile for evaluate() signal scoring and coach analysis

Usage:
    pi = ProfileIntelligence(org_id="hussi", agent_id="hussain")
    effective = pi.get_effective_profile()  # OrgProfileDef or None
    ctx = pi.enrich_context(context)        # adds profile hints to evaluate()
    report = pi.get_profile_report()        # dashboard summary
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("sentigent.profile_intelligence")


# ── Built-in org profile templates ──────────────────────────────────────────

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "product_manager": {
        "role": "product_manager",
        "description": (
            "Product manager perspective: prioritize user value and impact. "
            "Be cautious about over-engineering, scope creep, and changes that "
            "don't directly serve user needs."
        ),
        "value_weights": {
            "user_impact": 1.0,
            "delivery_speed": 0.8,
            "code_quality": 0.6,
            "technical_debt": 0.4,
            "safety": 0.9,
        },
        "thresholds": {
            "caution_threshold": 2.5,      # less hair-trigger than default
            "doubt_threshold": 0.5,
            "confidence_fast_path": 0.85,
        },
        "ai_context_hint": (
            "Think like a product manager: prioritize user value and feature delivery. "
            "Flag when agents over-engineer, refactor unnecessarily, or ignore user stories. "
            "Encourage breaking work into user-visible increments."
        ),
        "default_policies": [
            {
                "policy_name": "pm_no_scope_creep",
                "trigger_tool": "*",
                "trigger_pattern": r"refactor|cleanup|restructure|rewrite",
                "enforce_action": "slow_down",
                "enforce_reason": "PM profile: verify this refactor aligns with current sprint goals",
                "severity": "low",
            }
        ],
    },
    "security_engineer": {
        "role": "security_engineer",
        "description": (
            "Security-first perspective: all code changes evaluated for security implications. "
            "Strict on secrets handling, input validation, authentication, and compliance."
        ),
        "value_weights": {
            "security": 1.0,
            "compliance": 0.95,
            "correctness": 0.85,
            "performance": 0.5,
            "delivery_speed": 0.3,
        },
        "thresholds": {
            "caution_threshold": 1.5,      # more sensitive
            "doubt_threshold": 0.7,
            "confidence_fast_path": 0.95,  # very high bar for fast-path
        },
        "ai_context_hint": (
            "Think like a security engineer: flag any operations touching credentials, "
            "secrets, authentication, or user data. Be extra cautious about shell commands "
            "that could expose sensitive information. Check for injection risks."
        ),
        "default_policies": [
            {
                "policy_name": "sec_no_plaintext_secrets",
                "trigger_tool": "Write",
                "trigger_pattern": r"(api_key|password|secret|token)\s*=\s*['\"][^'\"]{8,}",
                "enforce_action": "block",
                "enforce_reason": "Security: never write credentials as plaintext in code files",
                "severity": "critical",
            },
            {
                "policy_name": "sec_env_file_writes",
                "trigger_tool": "Write",
                "trigger_pattern": r"\.env$|\.env\.",
                "enforce_action": "slow_down",
                "enforce_reason": "Security: verify .env file change is intentional and safe",
                "severity": "high",
            },
        ],
    },
    "data_analyst": {
        "role": "data_analyst",
        "description": (
            "Data analytics perspective: cautious about destructive DB operations, "
            "data migrations, and queries that could corrupt or lose data. "
            "Prefers read-only queries and reversible operations."
        ),
        "value_weights": {
            "data_integrity": 1.0,
            "accuracy": 0.95,
            "reversibility": 0.85,
            "performance": 0.7,
            "speed": 0.4,
        },
        "thresholds": {
            "caution_threshold": 1.8,
            "doubt_threshold": 0.65,
            "confidence_fast_path": 0.90,
        },
        "ai_context_hint": (
            "Think like a data analyst: prioritize data integrity and query correctness. "
            "Flag any DELETE/DROP/TRUNCATE statements, irreversible migrations, or "
            "queries lacking WHERE clauses. Suggest dry-runs before mutations."
        ),
        "default_policies": [
            {
                "policy_name": "da_no_unqualified_delete",
                "trigger_tool": "Bash",
                "trigger_pattern": r"\bDELETE\b(?!.*\bWHERE\b)",
                "enforce_action": "escalate",
                "enforce_reason": "Data: DELETE without WHERE will wipe the entire table",
                "severity": "critical",
            }
        ],
    },
    "devops_engineer": {
        "role": "devops_engineer",
        "description": (
            "DevOps/SRE perspective: infrastructure changes evaluated for stability, "
            "blast radius, and rollback capability. Conservative on production deployments."
        ),
        "value_weights": {
            "system_stability": 1.0,
            "availability": 0.95,
            "rollback_capability": 0.9,
            "security": 0.85,
            "deployment_speed": 0.5,
        },
        "thresholds": {
            "caution_threshold": 1.6,
            "doubt_threshold": 0.65,
            "confidence_fast_path": 0.93,
        },
        "ai_context_hint": (
            "Think like a DevOps engineer: evaluate infrastructure changes for blast radius "
            "and rollback capability. Flag force pushes, production config changes, and "
            "deployments without health checks or staged rollouts."
        ),
        "default_policies": [
            {
                "policy_name": "devops_no_force_push",
                "trigger_tool": "Bash",
                "trigger_pattern": r"git push.*--force|git push.*-f\b",
                "enforce_action": "escalate",
                "enforce_reason": "DevOps: force push can overwrite shared history",
                "severity": "high",
            },
            {
                "policy_name": "devops_deploy_review",
                "trigger_tool": "Bash",
                "trigger_pattern": r"\b(deploy|kubectl apply|terraform apply|ansible-playbook)\b",
                "enforce_action": "slow_down",
                "enforce_reason": "DevOps: verify deployment target and rollback plan",
                "severity": "medium",
            },
        ],
    },
}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class OrgProfileDef:
    """An org-level profile definition, either from Supabase or built-in."""

    profile_name: str
    org_id: str
    role: str                              # "product_manager", "security_engineer", ...
    description: str = ""
    value_weights: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    ai_context_hint: str = ""
    agent_ids: list[str] = field(default_factory=list)  # empty = all agents
    default_policies: list[dict[str, Any]] = field(default_factory=list)
    is_active: bool = True
    source: str = "supabase"               # "supabase" or "builtin"

    def applies_to(self, agent_id: str) -> bool:
        """Return True if this profile applies to the given agent."""
        return not self.agent_ids or agent_id in self.agent_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "org_id": self.org_id,
            "role": self.role,
            "description": self.description,
            "value_weights": self.value_weights,
            "thresholds": self.thresholds,
            "ai_context_hint": self.ai_context_hint,
            "agent_ids": self.agent_ids,
            "is_active": self.is_active,
            "source": self.source,
        }


@dataclass
class ProfileReport:
    """Summary of the current profile state for an agent."""

    agent_id: str
    org_id: str
    active_profile: str             # profile name or "default"
    role: str
    description: str
    value_weights: dict[str, float]
    thresholds: dict[str, float]
    ai_context_hint: str
    available_profiles: list[str]   # all profiles available for this org
    policy_templates_count: int     # default policies this profile would seed

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "active_profile": self.active_profile,
            "role": self.role,
            "description": self.description,
            "value_weights": self.value_weights,
            "thresholds": self.thresholds,
            "ai_context_hint": self.ai_context_hint,
            "available_profiles": self.available_profiles,
            "policy_templates_count": self.policy_templates_count,
        }


# ── Profile Intelligence ─────────────────────────────────────────────────────


class ProfileIntelligence:
    """Manages org-level profiles and applies them to agent evaluation.

    Profiles loaded from Supabase override built-in profiles for the same role.
    Profiles are cached for 5 minutes.

    Usage:
        pi = ProfileIntelligence(org_id="hussi", agent_id="hussain")
        profile = pi.get_effective_profile()
        ctx = pi.enrich_context({"tool_name": "Bash", ...})
    """

    _CACHE_TTL_SECONDS = 300

    def __init__(self, org_id: str, agent_id: str = "") -> None:
        self.org_id = org_id
        self.agent_id = agent_id
        self._profiles: list[OrgProfileDef] = []
        self._active_role: str = ""           # role assigned via Supabase
        self._last_refresh: float = 0.0
        self._lock = threading.Lock()
        self._supabase_client: Any = None

    def _get_client(self) -> Any:
        if self._supabase_client is not None:
            return self._supabase_client
        try:
            import os
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL", "")
            key = (
                os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                or os.environ.get("SUPABASE_ANON_KEY", "")
            )
            if url and key:
                self._supabase_client = create_client(url, key)
        except Exception:
            pass
        return self._supabase_client

    def refresh(self, force: bool = False) -> None:
        """Refresh profile definitions and agent assignment from Supabase."""
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self._CACHE_TTL_SECONDS:
            return

        client = self._get_client()
        if not client:
            with self._lock:
                self._last_refresh = now
            return

        profiles: list[OrgProfileDef] = []
        active_role = ""

        try:
            # Load all active profiles for this org
            result = (
                client.table("org_profiles")
                .select(
                    "profile_name,role,description,value_weights,thresholds,"
                    "ai_context_hint,agent_ids,default_policies,is_active"
                )
                .eq("org_id", self.org_id)
                .eq("is_active", True)
                .execute()
            )
            for row in (result.data or []):
                def _parse_json(val: Any, default: Any) -> Any:
                    if isinstance(val, dict | list):
                        return val
                    if isinstance(val, str):
                        try:
                            return json.loads(val)
                        except Exception:
                            return default
                    return default

                profiles.append(OrgProfileDef(
                    profile_name=row.get("profile_name", ""),
                    org_id=self.org_id,
                    role=row.get("role", ""),
                    description=row.get("description", ""),
                    value_weights=_parse_json(row.get("value_weights"), {}),
                    thresholds=_parse_json(row.get("thresholds"), {}),
                    ai_context_hint=row.get("ai_context_hint", ""),
                    agent_ids=_parse_json(row.get("agent_ids"), []),
                    default_policies=_parse_json(row.get("default_policies"), []),
                    is_active=bool(row.get("is_active", True)),
                    source="supabase",
                ))
        except Exception as exc:
            logger.debug("Profile refresh failed: %s", exc)

        try:
            # Load agent assignment: which profile is this agent assigned?
            result2 = (
                client.table("agent_profile_assignments")
                .select("profile_name")
                .eq("org_id", self.org_id)
                .eq("agent_id", self.agent_id)
                .execute()
            )
            rows = result2.data or []
            if rows:
                active_role = rows[0].get("profile_name", "")
        except Exception as exc:
            logger.debug("Agent profile assignment query failed: %s", exc)

        with self._lock:
            self._profiles = profiles
            # Only update _active_role from Supabase if it returned a non-empty value.
            # This preserves locally-assigned profiles (via assign_profile) when
            # the agent has no Supabase assignment yet.
            if active_role:
                self._active_role = active_role
            self._last_refresh = now

        logger.debug(
            "Profile intelligence refreshed: %d profiles, active_role=%s",
            len(profiles), active_role or "default",
        )

    def get_effective_profile(self) -> OrgProfileDef | None:
        """Get the profile currently effective for this agent.

        Lookup order:
        1. Supabase org profile assigned to this agent_id
        2. Supabase org default profile for this org
        3. Built-in profile matching the active role
        4. None (use default engine behavior)
        """
        self.refresh()

        with self._lock:
            profiles = list(self._profiles)
            active_role = self._active_role

        # Try Supabase profiles first
        if profiles:
            # Agent-specific assignment
            if active_role:
                for p in profiles:
                    if p.profile_name == active_role and p.applies_to(self.agent_id):
                        return p
            # Org-default (agent_ids is empty = applies to all)
            for p in profiles:
                if not p.agent_ids:
                    return p

        # Fall back to built-in profile
        if active_role and active_role in BUILTIN_PROFILES:
            tmpl = BUILTIN_PROFILES[active_role]
            return OrgProfileDef(
                profile_name=active_role,
                org_id=self.org_id,
                role=active_role,
                description=tmpl.get("description", ""),
                value_weights=tmpl.get("value_weights", {}),
                thresholds=tmpl.get("thresholds", {}),
                ai_context_hint=tmpl.get("ai_context_hint", ""),
                default_policies=tmpl.get("default_policies", []),
                source="builtin",
            )

        return None

    def enrich_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Inject profile-level hints into evaluate() context.

        This allows the signal engine to apply role-specific scoring biases.
        Returns the enriched context dict (original is not modified).
        """
        profile = self.get_effective_profile()
        if not profile:
            return context

        enriched = dict(context)
        enriched["_profile_intelligence"] = {
            "role": profile.role,
            "ai_context_hint": profile.ai_context_hint,
            "value_weights": profile.value_weights,
            "thresholds": profile.thresholds,
        }
        return enriched

    def get_profile_report(self) -> ProfileReport:
        """Build a ProfileReport for dashboard display."""
        self.refresh()

        with self._lock:
            profiles = list(self._profiles)
            active_role = self._active_role

        effective = self.get_effective_profile()

        # Available profiles = Supabase profiles + built-in profiles
        available = list(BUILTIN_PROFILES.keys())
        for p in profiles:
            if p.profile_name not in available:
                available.append(p.profile_name)
        available.sort()

        if effective:
            return ProfileReport(
                agent_id=self.agent_id,
                org_id=self.org_id,
                active_profile=effective.profile_name,
                role=effective.role,
                description=effective.description,
                value_weights=effective.value_weights,
                thresholds=effective.thresholds,
                ai_context_hint=effective.ai_context_hint,
                available_profiles=available,
                policy_templates_count=len(effective.default_policies),
            )

        return ProfileReport(
            agent_id=self.agent_id,
            org_id=self.org_id,
            active_profile="default",
            role="default",
            description="No org profile assigned. Using default judgment settings.",
            value_weights={},
            thresholds={},
            ai_context_hint="",
            available_profiles=available,
            policy_templates_count=0,
        )

    def seed_default_policies(self, policy_engine_add_fn: Any) -> int:
        """Seed the org's policy engine with this profile's default policies.

        Calls policy_engine_add_fn(policy_dict) for each default policy.
        Returns the number of policies seeded.
        """
        profile = self.get_effective_profile()
        if not profile or not profile.default_policies:
            return 0

        count = 0
        for policy in profile.default_policies:
            try:
                policy_engine_add_fn({**policy, "org_id": self.org_id})
                count += 1
            except Exception as exc:
                logger.debug("Failed to seed policy %s: %s", policy.get("policy_name"), exc)
        return count

    def assign_profile(self, profile_name: str) -> bool:
        """Assign a profile to this agent. Persists to Supabase if available.

        Returns True if the assignment was saved to Supabase.
        """
        with self._lock:
            self._active_role = profile_name
            # Don't reset _last_refresh — the local assignment should persist
            # for the TTL window without being overwritten by a Supabase re-fetch.

        client = self._get_client()
        if not client:
            return False

        try:
            # Upsert agent → profile assignment
            client.table("agent_profile_assignments").upsert({
                "org_id": self.org_id,
                "agent_id": self.agent_id,
                "profile_name": profile_name,
            }).execute()
            logger.info("Assigned profile %s to agent %s", profile_name, self.agent_id)
            return True
        except Exception as exc:
            logger.debug("Failed to save profile assignment: %s", exc)
            return False

    @staticmethod
    def list_builtin_profiles() -> list[dict[str, str]]:
        """Return brief descriptions of all built-in profiles."""
        return [
            {"name": name, "description": tmpl.get("description", "")[:120]}
            for name, tmpl in BUILTIN_PROFILES.items()
        ]


# ── Singleton per (org_id, agent_id) ────────────────────────────────────────

_instances: dict[str, ProfileIntelligence] = {}
_instances_lock = threading.Lock()


def get_profile_intelligence(org_id: str, agent_id: str = "") -> ProfileIntelligence:
    """Get or create a ProfileIntelligence instance for the given org + agent."""
    key = f"{org_id}:{agent_id}"
    with _instances_lock:
        if key not in _instances:
            _instances[key] = ProfileIntelligence(org_id=org_id, agent_id=agent_id)
        return _instances[key]
