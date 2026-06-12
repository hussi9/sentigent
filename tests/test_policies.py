"""Tests for the Sentigent policy engine.

Tests cover:
- Policy loading from JSON file and defaults
- Policy checking against tool invocations
- All matching modes: contains, also_contains, contains_any, not_contains, regex
- Numeric thresholds (lines_changed_gt)
- Tool filtering
- Violation severity ordering
- Override action resolution
- Policy enable/disable
- Serialization round-trip
- Default policy effectiveness
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sentigent.policies import (
    DEFAULT_POLICIES,
    Policy,
    Violation,
    check_policies,
    create_default_policies,
    get_override_action,
    load_policies,
    save_policies,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_policies_path(tmp_path: Path) -> Path:
    """Provide a temporary path for policies.json."""
    return tmp_path / "policies.json"


@pytest.fixture
def sample_policies() -> list[Policy]:
    """Provide a small set of test policies."""
    return [
        Policy(
            id="no-force-push",
            name="No force push to main",
            rule={
                "tool": "Bash",
                "contains": ["push --force"],
                "also_contains": ["main", "master"],
            },
            action="escalate",
            severity="critical",
            message="Force pushing to main/master is prohibited",
        ),
        Policy(
            id="large-edit-review",
            name="Review large edits",
            rule={
                "tool": "Write|Edit",
                "lines_changed_gt": 100,
            },
            action="slow_down",
            severity="warning",
            message="Large changes need review",
        ),
        Policy(
            id="no-env-commit",
            name="No .env commits",
            rule={
                "tool": "Bash",
                "contains": ["git add"],
                "also_contains": [".env"],
            },
            action="escalate",
            severity="critical",
            message="Do not commit .env files",
        ),
    ]


# ─── Policy Loading Tests ──────────────────────────────────────────────────

class TestLoadPolicies:
    """Tests for policy loading."""

    def test_load_defaults_when_no_file(self, tmp_path: Path) -> None:
        """When no file exists, load built-in defaults."""
        policies = load_policies(tmp_path / "nonexistent.json")
        assert len(policies) == len(DEFAULT_POLICIES)
        assert all(isinstance(p, Policy) for p in policies)

    def test_load_from_file(self, tmp_policies_path: Path) -> None:
        """Load policies from a JSON file."""
        data = {
            "policies": [
                {
                    "id": "test-policy",
                    "name": "Test Policy",
                    "rule": {"tool": "Bash", "contains": ["echo"]},
                    "action": "slow_down",
                    "severity": "info",
                    "message": "Just a test",
                }
            ]
        }
        tmp_policies_path.write_text(json.dumps(data))

        policies = load_policies(tmp_policies_path)
        assert len(policies) == 1
        assert policies[0].id == "test-policy"
        assert policies[0].name == "Test Policy"
        assert policies[0].action == "slow_down"
        assert policies[0].severity == "info"

    def test_load_corrupted_file_returns_defaults(self, tmp_policies_path: Path) -> None:
        """Corrupted JSON falls back to defaults."""
        tmp_policies_path.write_text("{invalid json")
        policies = load_policies(tmp_policies_path)
        assert len(policies) == len(DEFAULT_POLICIES)

    def test_load_empty_policies_array(self, tmp_policies_path: Path) -> None:
        """Empty policies array returns empty list."""
        data = {"policies": []}
        tmp_policies_path.write_text(json.dumps(data))
        policies = load_policies(tmp_policies_path)
        assert policies == []

    def test_policy_enabled_default(self) -> None:
        """Policies default to enabled=True."""
        p = Policy.from_dict({
            "id": "test", "name": "Test", "rule": {},
            "action": "slow_down", "severity": "info", "message": "test",
        })
        assert p.enabled is True

    def test_policy_disabled(self) -> None:
        """Can create disabled policies."""
        p = Policy.from_dict({
            "id": "test", "name": "Test", "rule": {},
            "action": "slow_down", "severity": "info", "message": "test",
            "enabled": False,
        })
        assert p.enabled is False


# ─── Policy Saving Tests ───────────────────────────────────────────────────

class TestSavePolicies:
    """Tests for saving policies."""

    def test_save_and_reload(self, tmp_policies_path: Path, sample_policies: list[Policy]) -> None:
        """Policies survive a save → load round trip."""
        save_policies(sample_policies, tmp_policies_path)
        loaded = load_policies(tmp_policies_path)

        assert len(loaded) == len(sample_policies)
        for orig, loaded_p in zip(sample_policies, loaded):
            assert orig.id == loaded_p.id
            assert orig.name == loaded_p.name
            assert orig.action == loaded_p.action
            assert orig.severity == loaded_p.severity
            assert orig.message == loaded_p.message
            assert orig.rule == loaded_p.rule

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save_policies creates parent directories."""
        deep_path = tmp_path / "a" / "b" / "c" / "policies.json"
        save_policies([], deep_path)
        assert deep_path.exists()

    def test_serialization_round_trip(self, sample_policies: list[Policy]) -> None:
        """Policy.to_dict() and Policy.from_dict() are inverses."""
        for p in sample_policies:
            d = p.to_dict()
            rebuilt = Policy.from_dict(d)
            assert p.id == rebuilt.id
            assert p.name == rebuilt.name
            assert p.rule == rebuilt.rule
            assert p.action == rebuilt.action
            assert p.severity == rebuilt.severity
            assert p.message == rebuilt.message
            assert p.enabled == rebuilt.enabled


# ─── Create Default Policies Tests ─────────────────────────────────────────

class TestCreateDefaultPolicies:
    """Tests for create_default_policies."""

    def test_creates_file_if_missing(self, tmp_policies_path: Path) -> None:
        """Creates policies.json with defaults if it doesn't exist."""
        policies = create_default_policies(tmp_policies_path)
        assert tmp_policies_path.exists()
        assert len(policies) == len(DEFAULT_POLICIES)

    def test_doesnt_overwrite_existing(self, tmp_policies_path: Path) -> None:
        """If file already exists, load it instead of overwriting."""
        data = {"policies": [{"id": "custom", "name": "Custom", "rule": {},
                              "action": "enrich", "severity": "info",
                              "message": "custom rule"}]}
        tmp_policies_path.write_text(json.dumps(data))

        policies = create_default_policies(tmp_policies_path)
        assert len(policies) == 1
        assert policies[0].id == "custom"


# ─── Policy Checking: Contains ──────────────────────────────────────────────

class TestCheckContains:
    """Tests for 'contains' matching (ALL must match)."""

    def test_all_contains_match(self, sample_policies: list[Policy]) -> None:
        """Violation when all 'contains' strings found."""
        violations = check_policies(
            "Bash",
            "git push --force origin main",
            sample_policies,
        )
        assert len(violations) >= 1
        assert any(v.policy_id == "no-force-push" for v in violations)

    def test_partial_contains_no_match(self, sample_policies: list[Policy]) -> None:
        """No violation when only some 'contains' strings match."""
        violations = check_policies(
            "Bash",
            "git push --force origin feature-branch",
            sample_policies,
        )
        # force-push policy requires "main" or "master" in also_contains
        force_push_violations = [v for v in violations if v.policy_id == "no-force-push"]
        assert len(force_push_violations) == 0

    def test_case_insensitive(self, sample_policies: list[Policy]) -> None:
        """Matching is case-insensitive."""
        violations = check_policies(
            "Bash",
            "git PUSH --FORCE origin MAIN",
            sample_policies,
        )
        assert any(v.policy_id == "no-force-push" for v in violations)


# ─── Policy Checking: Also Contains ────────────────────────────────────────

class TestCheckAlsoContains:
    """Tests for 'also_contains' matching (at least ONE must match)."""

    def test_also_contains_main(self, sample_policies: list[Policy]) -> None:
        """Matches when 'main' is in input."""
        violations = check_policies(
            "Bash",
            "git push --force origin main",
            sample_policies,
        )
        assert any(v.policy_id == "no-force-push" for v in violations)

    def test_also_contains_master(self, sample_policies: list[Policy]) -> None:
        """Matches when 'master' is in input."""
        violations = check_policies(
            "Bash",
            "git push --force origin master",
            sample_policies,
        )
        assert any(v.policy_id == "no-force-push" for v in violations)

    def test_also_contains_neither(self, sample_policies: list[Policy]) -> None:
        """No match when neither 'main' nor 'master' present."""
        violations = check_policies(
            "Bash",
            "git push --force origin develop",
            sample_policies,
        )
        force_push_violations = [v for v in violations if v.policy_id == "no-force-push"]
        assert len(force_push_violations) == 0


# ─── Policy Checking: Contains Any ─────────────────────────────────────────

class TestCheckContainsAny:
    """Tests for 'contains_any' matching (at least ONE must match)."""

    def test_contains_any_matches_first(self) -> None:
        """Matches when first contains_any item found."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "contains_any": ["DROP TABLE", "TRUNCATE"]},
        )
        violations = check_policies("Bash", "psql -c 'DROP TABLE users'", [policy])
        assert len(violations) == 1

    def test_contains_any_matches_second(self) -> None:
        """Matches when second contains_any item found."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "contains_any": ["DROP TABLE", "TRUNCATE"]},
        )
        violations = check_policies("Bash", "psql -c 'TRUNCATE users'", [policy])
        assert len(violations) == 1

    def test_contains_any_no_match(self) -> None:
        """No violation when none of contains_any items found."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "contains_any": ["DROP TABLE", "TRUNCATE"]},
        )
        violations = check_policies("Bash", "psql -c 'SELECT * FROM users'", [policy])
        assert len(violations) == 0


# ─── Policy Checking: Not Contains ─────────────────────────────────────────

class TestCheckNotContains:
    """Tests for 'not_contains' matching (NONE should match)."""

    def test_not_contains_blocks_match(self) -> None:
        """If not_contains item found, no violation (excluded)."""
        policy = Policy(
            id="test", name="Test", action="slow_down", severity="warning",
            message="test",
            rule={"tool": "Bash", "contains": ["deploy"],
                  "not_contains": ["--dry-run"]},
        )
        # dry-run should be excluded
        violations = check_policies("Bash", "deploy --dry-run", [policy])
        assert len(violations) == 0

    def test_not_contains_allows_match(self) -> None:
        """If not_contains items absent, violation fires."""
        policy = Policy(
            id="test", name="Test", action="slow_down", severity="warning",
            message="test",
            rule={"tool": "Bash", "contains": ["deploy"],
                  "not_contains": ["--dry-run"]},
        )
        violations = check_policies("Bash", "deploy production", [policy])
        assert len(violations) == 1


# ─── Policy Checking: Regex ─────────────────────────────────────────────────

class TestCheckRegex:
    """Tests for regex-based matching."""

    def test_regex_matches(self) -> None:
        """Violation when regex pattern matches."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "regex": r"rm\s+-rf\s+/"},
        )
        violations = check_policies("Bash", "rm -rf /var/data", [policy])
        assert len(violations) == 1

    def test_regex_no_match(self) -> None:
        """No violation when regex doesn't match."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "regex": r"rm\s+-rf\s+/"},
        )
        violations = check_policies("Bash", "ls -la /var/data", [policy])
        assert len(violations) == 0

    def test_invalid_regex_skipped(self) -> None:
        """Invalid regex is silently skipped (no crash)."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test",
            rule={"tool": "Bash", "regex": "[invalid("},
        )
        violations = check_policies("Bash", "some input", [policy])
        assert len(violations) == 0


# ─── Policy Checking: Numeric Thresholds ────────────────────────────────────

class TestCheckNumericThresholds:
    """Tests for numeric threshold matching (lines_changed_gt)."""

    def test_lines_over_threshold(self, sample_policies: list[Policy]) -> None:
        """Violation when lines changed exceeds threshold."""
        violations = check_policies(
            "Write",
            "some file content",
            sample_policies,
            context={"lines_changed": 150},
        )
        assert any(v.policy_id == "large-edit-review" for v in violations)

    def test_lines_at_threshold(self, sample_policies: list[Policy]) -> None:
        """No violation when lines changed equals threshold (need > not >=)."""
        violations = check_policies(
            "Edit",
            "some file content",
            sample_policies,
            context={"lines_changed": 100},
        )
        large_violations = [v for v in violations if v.policy_id == "large-edit-review"]
        assert len(large_violations) == 0

    def test_lines_under_threshold(self, sample_policies: list[Policy]) -> None:
        """No violation when lines changed under threshold."""
        violations = check_policies(
            "Write",
            "some file content",
            sample_policies,
            context={"lines_changed": 50},
        )
        large_violations = [v for v in violations if v.policy_id == "large-edit-review"]
        assert len(large_violations) == 0

    def test_no_lines_in_context(self, sample_policies: list[Policy]) -> None:
        """No violation when lines_changed not in context (defaults to 0)."""
        violations = check_policies(
            "Write",
            "some content",
            sample_policies,
            context={},
        )
        large_violations = [v for v in violations if v.policy_id == "large-edit-review"]
        assert len(large_violations) == 0


# ─── Policy Checking: Tool Filtering ───────────────────────────────────────

class TestToolFiltering:
    """Tests for tool name filtering."""

    def test_wrong_tool_no_match(self, sample_policies: list[Policy]) -> None:
        """No violation when tool name doesn't match."""
        violations = check_policies(
            "Read",  # Not Bash — force-push policy shouldn't match
            "git push --force origin main",
            sample_policies,
        )
        force_push = [v for v in violations if v.policy_id == "no-force-push"]
        assert len(force_push) == 0

    def test_pipe_delimited_tool_match(self, sample_policies: list[Policy]) -> None:
        """Matches when tool is one of pipe-delimited options."""
        violations = check_policies(
            "Edit",
            "some content",
            sample_policies,
            context={"lines_changed": 200},
        )
        assert any(v.policy_id == "large-edit-review" for v in violations)

    def test_case_insensitive_tool(self) -> None:
        """Tool matching is case-insensitive."""
        policy = Policy(
            id="test", name="Test", action="slow_down", severity="info",
            message="test",
            rule={"tool": "bash", "contains": ["echo"]},
        )
        violations = check_policies("Bash", "echo hello", [policy])
        assert len(violations) == 1

    def test_no_tool_filter_matches_all(self) -> None:
        """Policy without tool filter matches any tool."""
        policy = Policy(
            id="test", name="Test", action="slow_down", severity="info",
            message="test",
            rule={"contains": ["danger"]},
        )
        violations = check_policies("AnyTool", "this is danger", [policy])
        assert len(violations) == 1


# ─── Disabled Policies ──────────────────────────────────────────────────────

class TestDisabledPolicies:
    """Tests for policy enable/disable."""

    def test_disabled_policy_skipped(self) -> None:
        """Disabled policies don't produce violations."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test", enabled=False,
            rule={"tool": "Bash", "contains": ["rm"]},
        )
        violations = check_policies("Bash", "rm -rf /", [policy])
        assert len(violations) == 0

    def test_enabled_policy_fires(self) -> None:
        """Enabled policies produce violations normally."""
        policy = Policy(
            id="test", name="Test", action="escalate", severity="critical",
            message="test", enabled=True,
            rule={"tool": "Bash", "contains": ["rm"]},
        )
        violations = check_policies("Bash", "rm -rf /", [policy])
        assert len(violations) == 1


# ─── Violation Ordering and Override ────────────────────────────────────────

class TestViolationOrdering:
    """Tests for violation severity ordering and override actions."""

    def test_critical_sorted_first(self) -> None:
        """Critical violations appear before warning violations."""
        policies = [
            Policy(id="warn", name="Warn", action="slow_down", severity="warning",
                   message="warning", rule={"contains": ["test"]}),
            Policy(id="crit", name="Crit", action="escalate", severity="critical",
                   message="critical", rule={"contains": ["test"]}),
        ]
        violations = check_policies("Bash", "test input", policies)
        assert len(violations) == 2
        assert violations[0].severity == "critical"
        assert violations[1].severity == "warning"

    def test_override_action_escalate(self) -> None:
        """get_override_action returns 'escalate' when any violation is critical."""
        violations = [
            Violation("a", "A", "warning", "slow_down", "msg"),
            Violation("b", "B", "critical", "escalate", "msg"),
        ]
        assert get_override_action(violations) == "escalate"

    def test_override_action_slow_down(self) -> None:
        """get_override_action returns 'slow_down' when no escalate."""
        violations = [
            Violation("a", "A", "warning", "slow_down", "msg"),
            Violation("b", "B", "info", "enrich", "msg"),
        ]
        assert get_override_action(violations) == "slow_down"

    def test_override_action_enrich(self) -> None:
        """get_override_action returns 'enrich' when no escalate or slow_down."""
        violations = [
            Violation("a", "A", "info", "enrich", "msg"),
        ]
        assert get_override_action(violations) == "enrich"

    def test_override_action_none(self) -> None:
        """get_override_action returns None for empty violations."""
        assert get_override_action([]) is None


# ─── Default Policy Effectiveness ───────────────────────────────────────────

class TestDefaultPolicies:
    """Tests that the built-in default policies actually catch things."""

    def test_catches_force_push_main(self) -> None:
        """Default policies catch force push to main."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git push --force origin main", policies)
        assert any(v.policy_id == "no-force-push" for v in violations)

    def test_catches_force_push_master(self) -> None:
        """Default policies catch force push to master."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git push -f origin master", policies)
        # Note: -f vs --force — "push -f" is in our contains list
        # Actually our contains has "push --force" and "push -f"
        assert any(v.policy_id == "no-force-push" for v in violations)

    def test_catches_env_commit(self) -> None:
        """Default policies catch .env in git add."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git add .env", policies)
        assert any(v.policy_id == "no-env-commits" for v in violations)

    def test_catches_hard_reset(self) -> None:
        """Default policies catch git reset --hard."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git reset --hard HEAD~3", policies)
        assert any(v.policy_id == "no-hard-reset" for v in violations)

    def test_catches_drop_table(self) -> None:
        """Default policies catch DROP TABLE."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "psql -c 'DROP TABLE users CASCADE'", policies)
        assert any(v.policy_id == "no-drop-table" for v in violations)

    def test_catches_rm_rf(self) -> None:
        """Default policies catch rm -rf."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "rm -rf /home/user/project", policies)
        assert any(v.policy_id == "no-rm-rf" for v in violations)

    def test_allows_normal_git_push(self) -> None:
        """Default policies don't flag normal git push."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git push origin main", policies)
        force_push = [v for v in violations if v.policy_id == "no-force-push"]
        assert len(force_push) == 0

    def test_allows_normal_git_add(self) -> None:
        """Default policies don't flag normal git add."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "git add src/main.py", policies)
        env_violations = [v for v in violations if v.policy_id == "no-env-commits"]
        assert len(env_violations) == 0

    def test_allows_normal_rm(self) -> None:
        """Default policies don't flag simple rm (no -rf)."""
        policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
        violations = check_policies("Bash", "rm file.txt", policies)
        rm_violations = [v for v in violations if v.policy_id == "no-rm-rf"]
        assert len(rm_violations) == 0


# ─── Violation Serialization ────────────────────────────────────────────────

class TestViolationSerialization:
    """Tests for Violation.to_dict() serialization."""

    def test_violation_to_dict(self) -> None:
        """Violation serializes to expected structure."""
        v = Violation(
            policy_id="test",
            policy_name="Test Policy",
            severity="critical",
            action="escalate",
            message="Test message",
            details={"tool": "Bash", "matched_contains": ["push"]},
        )
        d = v.to_dict()
        assert d["policy_id"] == "test"
        assert d["policy_name"] == "Test Policy"
        assert d["severity"] == "critical"
        assert d["action"] == "escalate"
        assert d["message"] == "Test message"
        assert d["details"]["tool"] == "Bash"

    def test_violation_to_dict_json_serializable(self) -> None:
        """Violation.to_dict() produces JSON-serializable output."""
        v = Violation("id", "name", "warning", "slow_down", "msg", {"key": "val"})
        # Should not raise
        json.dumps(v.to_dict())


# ─── Edge Cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests."""

    def test_empty_input(self, sample_policies: list[Policy]) -> None:
        """Empty tool input doesn't crash."""
        violations = check_policies("Bash", "", sample_policies)
        # Should not crash, may or may not match depending on policy rules
        assert isinstance(violations, list)

    def test_empty_policies_list(self) -> None:
        """Empty policies list returns no violations."""
        violations = check_policies("Bash", "rm -rf /", [])
        assert violations == []

    def test_policy_with_empty_rule(self) -> None:
        """Policy with empty rule matches everything."""
        policy = Policy(
            id="catch-all", name="Catch All", action="slow_down",
            severity="info", message="catch-all rule", rule={},
        )
        violations = check_policies("Bash", "any command", [policy])
        assert len(violations) == 1

    def test_multiple_violations(self) -> None:
        """Multiple policies can fire on the same input."""
        policies = [
            Policy(id="p1", name="P1", action="escalate", severity="critical",
                   message="msg1", rule={"contains": ["danger"]}),
            Policy(id="p2", name="P2", action="slow_down", severity="warning",
                   message="msg2", rule={"contains": ["danger"]}),
        ]
        violations = check_policies("Bash", "danger zone", policies)
        assert len(violations) == 2
