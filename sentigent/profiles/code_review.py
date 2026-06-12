"""Code Review profile — starter intuition for AI coding agents.

This profile provides day-1 baselines for agents in coding environments like
Claude Code, Cursor, Windsurf, and other AI-assisted development tools.

Covers:
- Destructive operations (rm, DROP, force-push)
- Change size and scope
- Test discipline
- Security hygiene (secrets, credentials)
- Deployment safety

Values: correctness > security > test_coverage > reversibility > speed
"""

from sentigent.core.types import Profile, ValueHierarchy, WorldModel


def create_code_review_profile() -> Profile:
    """Create the code_review domain profile."""
    return Profile(
        name="code_review",
        description=(
            "Coding judgment for AI-assisted development environments. "
            "Monitors code changes, CLI operations, deployments, and tests. "
            "Prioritizes correctness and security over speed."
        ),
        values=ValueHierarchy(
            values=[
                ("correctness", 1.0),      # Don't break things
                ("security", 0.95),        # No secrets, no vulnerabilities
                ("safety", 0.9),           # Reversibility, backups
                ("test_coverage", 0.8),    # Tests before changes
                ("reversibility", 0.7),    # Prefer reversible operations
                ("speed", 0.5),            # Velocity matters but less than safety
            ]
        ),
        world_model=WorldModel(
            baselines={
                # Session-level metrics
                "files_changed_per_session": {
                    "median": 4,
                    "mean": 6,
                    "std": 5,
                    "p5": 1,
                    "p25": 2,
                    "p75": 8,
                    "p95": 15,
                },
                # Edit-level metrics
                "lines_changed": {
                    "median": 20,
                    "mean": 45,
                    "std": 80,
                    "p5": 1,
                    "p25": 5,
                    "p75": 50,
                    "p95": 200,
                },
                # Outcomes
                "build_success_rate": {
                    "median": 0.85,
                    "mean": 0.82,
                    "std": 0.15,
                },
                "test_pass_rate": {
                    "median": 0.88,
                    "mean": 0.85,
                    "std": 0.12,
                },
                "deployment_success_rate": {
                    "median": 0.92,
                    "mean": 0.89,
                    "std": 0.1,
                },
                # Destructive operation indicators
                "consequence_severity": {
                    "median": 0.3,
                    "mean": 0.35,
                    "std": 0.25,
                    "p5": 0.1,
                    "p25": 0.2,
                    "p75": 0.5,
                    "p95": 0.9,
                },
            }
        ),
        signal_thresholds={
            "caution_threshold": 1.5,     # Lower threshold = more sensitive to anomalies in code
            "doubt_threshold": 0.5,        # Trigger enrichment more easily
            "urgency_threshold": 0.85,     # Urgency less relevant in coding
            "confidence_fast_path": 0.92,  # High bar for auto-approve in code changes
            "frustration_retries": 3,      # Build failing 3x = suggest different approach
        },
    )
