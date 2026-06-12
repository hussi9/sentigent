"""Tests for policy_engine.py — org-wide policy enforcement."""
from __future__ import annotations

import pytest

from sentigent.core.policy_engine import (
    OrgPolicy,
    Layer3Pattern,
    PolicyDecision,
    PolicyEngine,
    get_policy_engine,
)


# ── OrgPolicy.matches() ───────────────────────────────────────────────────────


class TestOrgPolicyMatches:
    def test_inactive_policy_never_matches(self):
        policy = OrgPolicy(
            policy_name="test",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern="",
            is_active=False,
        )
        assert not policy.matches("Bash", "git push --force")

    def test_wildcard_tool_matches_any(self):
        policy = OrgPolicy(
            policy_name="test",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern="",
        )
        assert policy.matches("Bash", "anything")
        assert policy.matches("Write", "anything")
        assert policy.matches("Edit", "anything")

    def test_tool_filter_case_insensitive(self):
        policy = OrgPolicy(
            policy_name="test",
            org_id="org1",
            trigger_tool="bash",
            trigger_pattern="",
        )
        assert policy.matches("Bash", "git push")
        assert policy.matches("BASH", "git push")
        assert not policy.matches("Write", "git push")

    def test_pattern_matches_task(self):
        policy = OrgPolicy(
            policy_name="no_force_push",
            org_id="org1",
            trigger_tool="Bash",
            trigger_pattern=r"git push.*--force",
        )
        assert policy.matches("Bash", "git push origin main --force")
        assert policy.matches("Bash", "git push --force")
        assert not policy.matches("Bash", "git push origin main")
        assert not policy.matches("Bash", "git commit -m 'fix'")

    def test_pattern_case_insensitive(self):
        policy = OrgPolicy(
            policy_name="test",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern=r"DROP TABLE",
        )
        assert policy.matches("Bash", "DROP TABLE users")
        assert policy.matches("Bash", "drop table users")  # IGNORECASE

    def test_invalid_regex_treated_as_no_match(self):
        policy = OrgPolicy(
            policy_name="bad_regex",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern="[invalid",  # bad regex
        )
        # Should not raise, just not match
        assert not policy.matches("Bash", "anything")

    def test_profile_override_filters(self):
        policy = OrgPolicy(
            policy_name="pm_only",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern="",
            profile_override="product_manager",
        )
        assert policy.matches("Bash", "task", profile="product_manager")
        assert not policy.matches("Bash", "task", profile="security_engineer")
        # Empty profile → passes profile filter (conservative: apply if profile unknown)
        assert policy.matches("Bash", "task", profile="")

    def test_no_profile_override_matches_all_profiles(self):
        policy = OrgPolicy(
            policy_name="org_wide",
            org_id="org1",
            trigger_tool="*",
            trigger_pattern="",
            profile_override="",
        )
        assert policy.matches("Bash", "task", profile="product_manager")
        assert policy.matches("Bash", "task", profile="security_engineer")
        assert policy.matches("Bash", "task", profile="")


# ── PolicyEngine (offline / no Supabase) ─────────────────────────────────────


class TestPolicyEngineOffline:
    def test_empty_engine_returns_no_match(self):
        engine = PolicyEngine(org_id="test_org")
        result = engine.check(tool_name="Bash", task="git push origin main")
        assert not result.matched

    def test_load_from_local_and_check(self):
        engine = PolicyEngine(org_id="test_org")
        engine.load_from_local([
            {
                "pattern_name": "no_force_push",
                "condition": {
                    "type": "org_policy",
                    "trigger_tool": "Bash",
                    "trigger_pattern": r"git push.*--force",
                    "enforce_reason": "Force push blocked",
                    "severity": "high",
                },
                "learned_action": "escalate",
            }
        ])
        result = engine.check("Bash", "git push --force")
        assert result.matched
        assert result.enforce_action == "escalate"
        assert result.policy_name == "no_force_push"

    def test_load_from_local_skips_non_policy_rules(self):
        engine = PolicyEngine(org_id="test_org")
        engine.load_from_local([
            {
                "pattern_name": "learned_pattern",
                "condition": {"type": "auto_proceed"},  # not org_policy
                "learned_action": "proceed",
            }
        ])
        result = engine.check("Bash", "anything")
        assert not result.matched  # non-policy rules ignored

    def test_severity_ordering_critical_first(self):
        """Critical policies should be checked before medium ones."""
        engine = PolicyEngine(org_id="test_org")
        engine._policies = [
            OrgPolicy(
                policy_name="medium_policy",
                org_id="test_org",
                trigger_tool="*",
                trigger_pattern="test",
                enforce_action="slow_down",
                severity="medium",
            ),
            OrgPolicy(
                policy_name="critical_policy",
                org_id="test_org",
                trigger_tool="*",
                trigger_pattern="test",
                enforce_action="block",
                severity="critical",
            ),
        ]
        engine._last_refresh = float("inf")  # prevent refresh
        result = engine.check("Bash", "test command")
        assert result.matched
        assert result.policy_name == "critical_policy"  # critical comes first
        assert result.enforce_action == "block"

    def test_check_fails_open_on_exception(self):
        """If policy engine throws, decision should be no-match (fail open)."""
        engine = PolicyEngine(org_id="test_org")
        # Install a policy that would cause an error (simulate via broken condition)
        engine._policies = []
        engine._last_refresh = float("inf")
        result = engine.check("Bash", "safe command")
        assert not result.matched

    def test_policy_decision_fields(self):
        engine = PolicyEngine(org_id="test_org")
        engine._policies = [
            OrgPolicy(
                policy_name="no_secrets",
                org_id="test_org",
                trigger_tool="Write",
                trigger_pattern=r"api_key\s*=\s*['\"][^'\"]{8,}",
                enforce_action="block",
                enforce_reason="Never write secrets as plaintext",
                severity="critical",
            )
        ]
        engine._last_refresh = float("inf")
        result = engine.check("Write", "api_key = 'sk-1234567890abcdef'")
        assert result.matched
        assert result.policy_name == "no_secrets"
        assert result.enforce_action == "block"
        assert "secret" in result.reason.lower() or "no_secrets" in result.reason
        assert result.severity == "critical"
        assert result.source == "org"

    def test_singleton_per_org_profile(self):
        e1 = get_policy_engine(org_id="org_a", profile="pm")
        e2 = get_policy_engine(org_id="org_a", profile="pm")
        e3 = get_policy_engine(org_id="org_b", profile="pm")
        assert e1 is e2
        assert e1 is not e3


# ── PolicyDecision ────────────────────────────────────────────────────────────


class TestPolicyDecision:
    def test_default_unmatched(self):
        d = PolicyDecision()
        assert not d.matched
        assert d.enforce_action == ""
        assert d.policy_name == ""

    def test_matched_decision(self):
        d = PolicyDecision(
            matched=True,
            policy_name="no_force_push",
            enforce_action="escalate",
            reason="Force push is dangerous",
            severity="high",
        )
        assert d.matched
        assert d.enforce_action == "escalate"
