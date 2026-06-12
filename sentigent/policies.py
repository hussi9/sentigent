"""Policy Engine — JSON-defined rules enforced before signal computation.

Policies are organizational guardrails stored in ~/.sentigent/policies.json
(Layer 1) or pushed from org-level config (Layer 2, future).

Policies are checked BEFORE signal computation in sentigent_evaluate().
Policy violations override signal-based decisions:
  - "escalate" always wins (critical violations block the action)
  - "slow_down" adds extra review
  - "enrich" requests more context

Usage:
    policies = load_policies()
    violations = check_policies("Bash", "git push --force origin main", policies)
    # violations = [Violation(policy_id="no-force-push", severity="critical", ...)]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Types ──────────────────────────────────────────────────────────────────

@dataclass
class Policy:
    """A single policy rule."""

    id: str
    name: str
    rule: dict[str, Any]
    action: str  # "escalate", "slow_down", "enrich"
    severity: str  # "critical", "warning", "info"
    message: str
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        """Create a Policy from a JSON dict."""
        return cls(
            id=data["id"],
            name=data["name"],
            rule=data.get("rule", {}),
            action=data.get("action", "slow_down"),
            severity=data.get("severity", "warning"),
            message=data.get("message", ""),
            enabled=data.get("enabled", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "rule": self.rule,
            "action": self.action,
            "severity": self.severity,
            "message": self.message,
            "enabled": self.enabled,
        }


@dataclass
class Violation:
    """A policy violation detected during evaluation."""

    policy_id: str
    policy_name: str
    severity: str  # "critical", "warning", "info"
    action: str  # "escalate", "slow_down", "enrich"
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON response."""
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "severity": self.severity,
            "action": self.action,
            "message": self.message,
            "details": self.details,
        }


# ─── Default Policies ───────────────────────────────────────────────────────

DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "id": "no-force-push",
        "name": "No force push to main",
        "rule": {
            "tool": "Bash",
            "contains_any": ["push --force", "push -f"],
            "also_contains": ["main", "master"],
        },
        "action": "escalate",
        "severity": "critical",
        "message": "Force pushing to main/master is prohibited by org policy",
    },
    {
        "id": "review-large-changes",
        "name": "Review changes over 100 lines",
        "rule": {
            "tool": "Write|Edit",
            "lines_changed_gt": 100,
        },
        "action": "slow_down",
        "severity": "warning",
        "message": "Changes over 100 lines require extra review per team policy",
    },
    {
        "id": "no-env-commits",
        "name": "Never commit .env files",
        "rule": {
            "tool": "Bash",
            "contains": ["git add"],
            "also_contains": [".env"],
        },
        "action": "escalate",
        "severity": "critical",
        "message": "Committing .env files is prohibited",
    },
    {
        "id": "no-hard-reset",
        "name": "No hard reset",
        "rule": {
            "tool": "Bash",
            "contains": ["reset --hard"],
        },
        "action": "escalate",
        "severity": "critical",
        "message": "Hard reset can destroy uncommitted work — escalating for human review",
    },
    {
        "id": "no-drop-table",
        "name": "No DROP TABLE",
        "rule": {
            "tool": "Bash",
            "contains_any": ["DROP TABLE", "DROP DATABASE", "TRUNCATE"],
        },
        "action": "escalate",
        "severity": "critical",
        "message": "Destructive database operations require human approval",
    },
    {
        "id": "no-rm-rf",
        "name": "No rm -rf",
        "rule": {
            "tool": "Bash",
            "regex": r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--force\s+--recursive|-[a-zA-Z]*f[a-zA-Z]*r)\b",
        },
        "action": "escalate",
        "severity": "critical",
        "message": "Recursive force-delete is prohibited — move files to .archive/ instead",
    },
]


# ─── Policy Storage ─────────────────────────────────────────────────────────

POLICIES_PATH = Path.home() / ".sentigent" / "policies.json"


def load_policies(path: str | Path | None = None) -> list[Policy]:
    """Load policies from JSON file.

    Falls back to DEFAULT_POLICIES if the file doesn't exist.

    Args:
        path: Path to policies.json. Defaults to ~/.sentigent/policies.json.

    Returns:
        List of Policy objects.
    """
    policies_path = Path(path) if path else POLICIES_PATH

    if policies_path.exists():
        try:
            with open(policies_path) as f:
                data = json.load(f)
            raw_policies = data.get("policies", [])
            return [Policy.from_dict(p) for p in raw_policies]
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupted file — fall back to defaults
            return [Policy.from_dict(p) for p in DEFAULT_POLICIES]

    # No file — use built-in defaults
    return [Policy.from_dict(p) for p in DEFAULT_POLICIES]


def save_policies(policies: list[Policy], path: str | Path | None = None) -> None:
    """Save policies to JSON file.

    Args:
        policies: List of Policy objects to save.
        path: Path to write. Defaults to ~/.sentigent/policies.json.
    """
    policies_path = Path(path) if path else POLICIES_PATH
    policies_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "policies": [p.to_dict() for p in policies],
    }
    with open(policies_path, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def create_default_policies(path: str | Path | None = None) -> list[Policy]:
    """Create the default policies file if it doesn't exist.

    Returns the loaded policies (either existing or newly created).
    """
    policies_path = Path(path) if path else POLICIES_PATH

    if policies_path.exists():
        return load_policies(policies_path)

    policies = [Policy.from_dict(p) for p in DEFAULT_POLICIES]
    save_policies(policies, policies_path)
    return policies


# ─── Policy Checking ────────────────────────────────────────────────────────

def check_policies(
    tool_name: str,
    tool_input: str,
    policies: list[Policy] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Violation]:
    """Check tool usage against all active policies.

    Args:
        tool_name: Name of the tool being used (e.g., "Bash", "Write", "Edit")
        tool_input: The input/command being sent to the tool
        policies: List of policies to check. Loads from disk if None.
        context: Optional context dict with additional metadata
            (e.g., {"lines_changed": 150})

    Returns:
        List of Violation objects for any policies that matched.
        Empty list if no violations detected.
    """
    if policies is None:
        policies = load_policies()

    context = context or {}
    violations: list[Violation] = []

    for policy in policies:
        if not policy.enabled:
            continue

        violation = _check_single_policy(policy, tool_name, tool_input, context)
        if violation is not None:
            violations.append(violation)

    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    violations.sort(key=lambda v: severity_order.get(v.severity, 99))

    return violations


def get_override_action(violations: list[Violation]) -> str | None:
    """Determine if violations should override the signal-based decision.

    Returns the most severe action from violations, or None if no override.
    Priority: escalate > slow_down > enrich > None
    """
    if not violations:
        return None

    # escalate is the strongest override
    for v in violations:
        if v.action == "escalate":
            return "escalate"

    for v in violations:
        if v.action == "slow_down":
            return "slow_down"

    for v in violations:
        if v.action == "enrich":
            return "enrich"

    return None


# ─── Internal Matching Logic ────────────────────────────────────────────────

def _check_single_policy(
    policy: Policy,
    tool_name: str,
    tool_input: str,
    context: dict[str, Any],
) -> Violation | None:
    """Check a single policy against the tool invocation.

    Returns a Violation if the policy was violated, else None.
    """
    rule = policy.rule

    # Step 1: Check tool filter
    tool_filter = rule.get("tool", "")
    if tool_filter:
        tool_patterns = [t.strip() for t in tool_filter.split("|")]
        if not any(t.lower() == tool_name.lower() for t in tool_patterns):
            return None  # Tool doesn't match — policy doesn't apply

    input_lower = tool_input.lower()

    # Step 2: Check "contains" — ALL must match
    contains_list = rule.get("contains", [])
    if contains_list:
        if not all(c.lower() in input_lower for c in contains_list):
            return None

    # Step 3: Check "also_contains" — at least ONE must match
    also_contains = rule.get("also_contains", [])
    if also_contains:
        if not any(c.lower() in input_lower for c in also_contains):
            return None

    # Step 4: Check "contains_any" — at least ONE must match
    contains_any = rule.get("contains_any", [])
    if contains_any:
        if not any(c.lower() in input_lower for c in contains_any):
            return None

    # Step 5: Check "not_contains" — NONE should match
    not_contains = rule.get("not_contains", [])
    if not_contains:
        if any(c.lower() in input_lower for c in not_contains):
            return None

    # Step 6: Check regex pattern
    regex_pattern = rule.get("regex", "")
    if regex_pattern:
        try:
            if not re.search(regex_pattern, tool_input, re.IGNORECASE):
                return None
        except re.error:
            return None  # Invalid regex — skip

    # Step 7: Check numeric thresholds from context
    lines_changed_gt = rule.get("lines_changed_gt")
    if lines_changed_gt is not None:
        actual_lines = context.get("lines_changed", 0)
        if actual_lines <= lines_changed_gt:
            return None

    # All checks passed — this is a violation
    details: dict[str, Any] = {
        "tool": tool_name,
        "matched_rule": rule,
    }

    # Add context about what matched
    if contains_list:
        matched_contains = [c for c in contains_list if c.lower() in input_lower]
        details["matched_contains"] = matched_contains
    if also_contains:
        matched_also = [c for c in also_contains if c.lower() in input_lower]
        details["matched_also_contains"] = matched_also
    if contains_any:
        matched_any = [c for c in contains_any if c.lower() in input_lower]
        details["matched_contains_any"] = matched_any

    return Violation(
        policy_id=policy.id,
        policy_name=policy.name,
        severity=policy.severity,
        action=policy.action,
        message=policy.message,
        details=details,
    )
