"""Org-wide policy enforcement engine (Layer 2 + Layer 3).

When an agent calls evaluate(), the PolicyEngine checks org-level policies FIRST,
before any individual signal computation. A matching policy overrides everything.

This is the enforcement layer:
- Layer 2: Org admin defines rules → all agents in org automatically follow them
- Layer 3: Cross-org anonymized patterns → industry-wide guardrails

Policy precedence (highest to lowest):
  1. Critical org policies (severity=critical)  → always enforced
  2. High org policies                           → enforced unless agent overrides
  3. Medium / low policies                       → advisory (slow_down / enrich)
  4. Layer 3 shared patterns                     → informational enrichment
  5. Local agent judgment                        → individual learning
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sentigent.policy_engine")


# ── Data Models ───────────────────────────────────────────────


@dataclass
class OrgPolicy:
    """A single org-wide policy rule."""

    policy_name: str
    org_id: str
    trigger_tool: str = "*"           # 'Bash', 'Write', 'Edit', '*'
    trigger_pattern: str = ""         # regex matched against task/tool_input
    profile_override: str = ""        # empty = all profiles
    enforce_action: str = "slow_down" # block, escalate, slow_down, enrich
    enforce_reason: str = ""
    severity: str = "medium"          # low, medium, high, critical
    is_active: bool = True

    def matches(self, tool_name: str, task: str, profile: str = "") -> bool:
        """Return True if this policy applies to the given tool call."""
        if not self.is_active:
            return False

        # Profile filter: if policy is scoped to a specific profile
        if self.profile_override and profile and self.profile_override != profile:
            return False

        # Tool filter
        if self.trigger_tool != "*" and self.trigger_tool.lower() != tool_name.lower():
            return False

        # Pattern filter
        if self.trigger_pattern:
            try:
                if not re.search(self.trigger_pattern, task, re.IGNORECASE):
                    return False
            except re.error:
                # Invalid regex → treat as no match
                return False

        return True


@dataclass
class Layer3Pattern:
    """An anonymized cross-org pattern from Layer 3."""

    pattern_name: str
    learned_action: str
    success_rate: float
    sample_size: int
    contributing_org_count: int = 1
    industry_tags: list[str] = field(default_factory=list)


@dataclass
class PolicyDecision:
    """Result of policy check — None if no policy matched."""

    matched: bool = False
    policy_name: str = ""
    enforce_action: str = ""
    reason: str = ""
    severity: str = ""
    source: str = "org"  # 'org' or 'layer3'


# ── Policy Engine ─────────────────────────────────────────────


class PolicyEngine:
    """Checks org policies and Layer 3 patterns before individual agent judgment.

    Policies are cached in memory and refreshed every 5 minutes from Supabase.
    On Supabase unavailability, falls back to cached policies silently.

    Usage:
        engine = PolicyEngine(org_id="hussi", profile="product_manager")
        decision = engine.check(tool_name="Bash", task="git push --force")
        if decision.matched:
            return decision.enforce_action, decision.reason
    """

    _CACHE_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, org_id: str, profile: str = "") -> None:
        self.org_id = org_id
        self.profile = profile
        self._policies: list[OrgPolicy] = []
        self._layer3_patterns: list[Layer3Pattern] = []
        self._last_refresh: float = 0.0
        self._lock = threading.Lock()
        self._supabase_client: Any = None

    def _get_client(self) -> Any:
        """Lazy Supabase client init."""
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
        """Refresh policies from Supabase if cache is stale."""
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self._CACHE_TTL_SECONDS:
            return

        client = self._get_client()
        if not client:
            return

        policies: list[OrgPolicy] = []
        layer3: list[Layer3Pattern] = []

        try:
            result = (
                client.table("org_policies")
                .select(
                    "policy_name,trigger_tool,trigger_pattern,profile_override,"
                    "enforce_action,enforce_reason,severity,is_active"
                )
                .eq("org_id", self.org_id)
                .eq("is_active", True)
                .execute()
            )
            for row in (result.data or []):
                policies.append(OrgPolicy(
                    policy_name=row.get("policy_name", ""),
                    org_id=self.org_id,
                    trigger_tool=row.get("trigger_tool", "*") or "*",
                    trigger_pattern=row.get("trigger_pattern", "") or "",
                    profile_override=row.get("profile_override", "") or "",
                    enforce_action=row.get("enforce_action", "slow_down"),
                    enforce_reason=row.get("enforce_reason", "") or "",
                    severity=row.get("severity", "medium") or "medium",
                    is_active=bool(row.get("is_active", True)),
                ))
        except Exception as exc:
            logger.debug("Policy refresh failed (org policies): %s", exc)

        try:
            result3 = (
                client.table("layer3_shared_patterns")
                .select("pattern_name,learned_action,success_rate,sample_size,contributing_org_count,industry_tags")
                .gte("sample_size", 100)
                .execute()
            )
            for row in (result3.data or []):
                layer3.append(Layer3Pattern(
                    pattern_name=row.get("pattern_name", ""),
                    learned_action=row.get("learned_action", "proceed"),
                    success_rate=float(row.get("success_rate", 0)),
                    sample_size=int(row.get("sample_size", 0)),
                    contributing_org_count=int(row.get("contributing_org_count", 1)),
                    industry_tags=row.get("industry_tags") or [],
                ))
        except Exception as exc:
            logger.debug("Policy refresh failed (layer3): %s", exc)

        with self._lock:
            self._policies = policies
            self._layer3_patterns = layer3
            self._last_refresh = time.monotonic()

        logger.debug(
            "Policies refreshed: %d org policies, %d layer3 patterns",
            len(policies), len(layer3),
        )

    def check(self, tool_name: str, task: str) -> PolicyDecision:
        """Check if any policy applies to this tool call.

        Policies are checked in severity order (critical first).
        Returns the first matching policy decision, or PolicyDecision(matched=False).

        Args:
            tool_name: The tool being called (e.g. 'Bash', 'Write')
            task: The tool input / task description

        Returns:
            PolicyDecision with matched=True if a policy fired.
        """
        self.refresh()

        with self._lock:
            policies = list(self._policies)

        # Sort by severity (critical first)
        _severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        policies.sort(key=lambda p: _severity_order.get(p.severity, 2))

        for policy in policies:
            if policy.matches(tool_name, task, self.profile):
                logger.debug(
                    "Policy matched: %s → %s (severity=%s)",
                    policy.policy_name, policy.enforce_action, policy.severity,
                )
                return PolicyDecision(
                    matched=True,
                    policy_name=policy.policy_name,
                    enforce_action=policy.enforce_action,
                    reason=policy.enforce_reason or f"Org policy: {policy.policy_name}",
                    severity=policy.severity,
                    source="org",
                )

        return PolicyDecision(matched=False)

    def record_violation(
        self,
        agent_id: str,
        policy_name: str,
        task: str,
        tool_name: str,
        enforced_action: str,
    ) -> None:
        """Log a policy violation to Supabase for governance reporting."""
        client = self._get_client()
        if not client:
            return
        try:
            client.table("policy_violations").insert({
                "org_id": self.org_id,
                "agent_id": agent_id,
                "policy_name": policy_name,
                "task": task[:500],
                "tool_name": tool_name,
                "enforced_action": enforced_action,
            }).execute()
            # Increment trigger_count on the policy (safe read-then-write)
            try:
                count_result = (
                    client.table("org_policies")
                    .select("trigger_count")
                    .eq("org_id", self.org_id)
                    .eq("policy_name", policy_name)
                    .execute()
                )
                if count_result.data:
                    new_count = (count_result.data[0].get("trigger_count") or 0) + 1
                    client.table("org_policies").update({
                        "trigger_count": new_count,
                        "last_triggered": datetime.now(timezone.utc).isoformat(),
                    }).eq("org_id", self.org_id).eq("policy_name", policy_name).execute()
            except Exception as _inc_exc:
                logger.debug("Failed to increment trigger_count: %s", _inc_exc)
        except Exception as exc:
            logger.debug("Failed to record policy violation: %s", exc)

    def load_from_local(self, rules: list[dict]) -> None:
        """Load policies from local SQLite org_patterns (offline fallback).

        Called by engine during Layer 2 pattern pull so policies work
        even without a live Supabase connection.
        """
        policies = []
        for rule in rules:
            cond = rule.get("condition", {})
            if isinstance(cond, str):
                import json
                try:
                    cond = json.loads(cond)
                except Exception:
                    cond = {}
            if not isinstance(cond, dict):
                cond = {}

            # Only load rules that look like org policies
            if cond.get("type") != "org_policy":
                continue

            policies.append(OrgPolicy(
                policy_name=rule.get("pattern_name", ""),
                org_id=self.org_id,
                trigger_tool=cond.get("trigger_tool", "*"),
                trigger_pattern=cond.get("trigger_pattern", ""),
                enforce_action=rule.get("learned_action", "slow_down"),
                enforce_reason=cond.get("enforce_reason", ""),
                severity=cond.get("severity", "medium"),
            ))

        with self._lock:
            # Merge with any existing Supabase-sourced policies
            existing_names = {p.policy_name for p in self._policies}
            for p in policies:
                if p.policy_name not in existing_names:
                    self._policies.append(p)
            # Prevent the next check() from immediately re-fetching from Supabase
            # and overwriting these locally-loaded policies.
            if not self._last_refresh:
                import time as _time
                self._last_refresh = _time.monotonic()


# ── Singleton per (org_id, profile) ──────────────────────────

_engines: dict[str, PolicyEngine] = {}
_engines_lock = threading.Lock()


def get_policy_engine(org_id: str, profile: str = "") -> PolicyEngine:
    """Get or create a PolicyEngine for the given org + profile."""
    key = f"{org_id}:{profile}"
    with _engines_lock:
        if key not in _engines:
            _engines[key] = PolicyEngine(org_id=org_id, profile=profile)
        return _engines[key]
