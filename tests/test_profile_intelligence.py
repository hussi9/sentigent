"""Tests for profile_intelligence.py — org-level profile management."""
from __future__ import annotations

import pytest

from sentigent.core.profile_intelligence import (
    BUILTIN_PROFILES,
    OrgProfileDef,
    ProfileIntelligence,
    ProfileReport,
    get_profile_intelligence,
)


# ── OrgProfileDef ─────────────────────────────────────────────────────────────


class TestOrgProfileDef:
    def test_applies_to_empty_agent_ids(self):
        """Empty agent_ids means applies to ALL agents."""
        profile = OrgProfileDef(
            profile_name="pm",
            org_id="org1",
            role="product_manager",
            agent_ids=[],
        )
        assert profile.applies_to("any_agent")
        assert profile.applies_to("")

    def test_applies_to_specific_agents(self):
        profile = OrgProfileDef(
            profile_name="pm",
            org_id="org1",
            role="product_manager",
            agent_ids=["alice", "bob"],
        )
        assert profile.applies_to("alice")
        assert profile.applies_to("bob")
        assert not profile.applies_to("charlie")

    def test_to_dict_contains_required_keys(self):
        profile = OrgProfileDef(
            profile_name="security",
            org_id="org2",
            role="security_engineer",
            description="Security focused",
            value_weights={"security": 1.0},
        )
        d = profile.to_dict()
        assert d["profile_name"] == "security"
        assert d["org_id"] == "org2"
        assert d["role"] == "security_engineer"
        assert d["value_weights"] == {"security": 1.0}
        assert "agent_ids" in d
        assert "is_active" in d


# ── ProfileIntelligence (offline / builtin mode) ──────────────────────────────


class TestProfileIntelligenceOffline:
    def setup_method(self):
        """Reset singleton for each test."""
        from sentigent.core.profile_intelligence import _instances
        _instances.clear()

    def test_default_profile_when_no_supabase(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="test_agent")
        # No Supabase configured → no effective profile
        effective = pi.get_effective_profile()
        assert effective is None

    def test_assign_builtin_profile_locally(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent1")
        pi.assign_profile("product_manager")
        effective = pi.get_effective_profile()
        assert effective is not None
        assert effective.role == "product_manager"
        assert effective.source == "builtin"
        assert effective.value_weights.get("user_impact") == 1.0

    def test_assign_security_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent2")
        pi.assign_profile("security_engineer")
        effective = pi.get_effective_profile()
        assert effective is not None
        assert effective.role == "security_engineer"
        assert effective.value_weights.get("security") == 1.0
        assert len(effective.default_policies) > 0

    def test_assign_data_analyst_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent3")
        pi.assign_profile("data_analyst")
        effective = pi.get_effective_profile()
        assert effective.role == "data_analyst"
        assert effective.value_weights.get("data_integrity") == 1.0

    def test_assign_devops_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent4")
        pi.assign_profile("devops_engineer")
        effective = pi.get_effective_profile()
        assert effective.role == "devops_engineer"
        assert effective.thresholds.get("caution_threshold") == 1.6

    def test_enrich_context_with_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent5")
        pi.assign_profile("product_manager")
        ctx = {"tool_name": "Bash", "confidence": 0.8}
        enriched = pi.enrich_context(ctx)
        assert "_profile_intelligence" in enriched
        pi_ctx = enriched["_profile_intelligence"]
        assert pi_ctx["role"] == "product_manager"
        assert "ai_context_hint" in pi_ctx
        assert "value_weights" in pi_ctx

    def test_enrich_context_no_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent6")
        ctx = {"tool_name": "Bash"}
        enriched = pi.enrich_context(ctx)
        # No profile → context unchanged
        assert "_profile_intelligence" not in enriched
        assert enriched == ctx

    def test_get_profile_report_no_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent7")
        report = pi.get_profile_report()
        assert isinstance(report, ProfileReport)
        assert report.active_profile == "default"
        assert report.role == "default"
        assert len(report.available_profiles) == len(BUILTIN_PROFILES)

    def test_get_profile_report_with_profile(self):
        pi = ProfileIntelligence(org_id="test_org", agent_id="agent8")
        pi.assign_profile("security_engineer")
        report = pi.get_profile_report()
        assert report.active_profile == "security_engineer"
        assert report.role == "security_engineer"
        assert report.policy_templates_count > 0
        assert report.to_dict()["active_profile"] == "security_engineer"

    def test_list_builtin_profiles(self):
        profiles = ProfileIntelligence.list_builtin_profiles()
        assert isinstance(profiles, list)
        names = [p["name"] for p in profiles]
        assert "product_manager" in names
        assert "security_engineer" in names
        assert "data_analyst" in names
        assert "devops_engineer" in names
        for p in profiles:
            assert "description" in p
            assert len(p["description"]) > 10

    def test_singleton_per_org_agent(self):
        pi1 = get_profile_intelligence(org_id="org_a", agent_id="agent_a")
        pi2 = get_profile_intelligence(org_id="org_a", agent_id="agent_a")
        pi3 = get_profile_intelligence(org_id="org_b", agent_id="agent_a")
        assert pi1 is pi2
        assert pi1 is not pi3


# ── BUILTIN_PROFILES structure ────────────────────────────────────────────────


class TestBuiltinProfiles:
    def test_all_profiles_have_required_fields(self):
        for name, tmpl in BUILTIN_PROFILES.items():
            assert "role" in tmpl, f"{name}: missing role"
            assert "description" in tmpl, f"{name}: missing description"
            assert "value_weights" in tmpl, f"{name}: missing value_weights"
            assert "thresholds" in tmpl, f"{name}: missing thresholds"
            assert "ai_context_hint" in tmpl, f"{name}: missing ai_context_hint"

    def test_value_weights_are_valid(self):
        for name, tmpl in BUILTIN_PROFILES.items():
            for key, val in tmpl["value_weights"].items():
                assert 0.0 <= val <= 1.0, f"{name}/{key}: weight {val} out of range"

    def test_security_profile_has_block_policy(self):
        policies = BUILTIN_PROFILES["security_engineer"]["default_policies"]
        block_policy = next(
            (p for p in policies if p["enforce_action"] == "block"),
            None,
        )
        assert block_policy is not None, "Security profile should have at least one block policy"

    def test_devops_profile_has_force_push_policy(self):
        policies = BUILTIN_PROFILES["devops_engineer"]["default_policies"]
        assert any("force" in p["trigger_pattern"] for p in policies)

    def test_data_analyst_has_delete_escalate(self):
        policies = BUILTIN_PROFILES["data_analyst"]["default_policies"]
        assert any(p["enforce_action"] == "escalate" for p in policies)

    def test_pm_profile_lower_caution_threshold(self):
        pm = BUILTIN_PROFILES["product_manager"]["thresholds"]
        sec = BUILTIN_PROFILES["security_engineer"]["thresholds"]
        # Security engineer should be MORE sensitive (lower threshold)
        assert pm["caution_threshold"] > sec["caution_threshold"]
