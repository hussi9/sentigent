"""Best-practices knowledge base — the benchmark a profile is reviewed against.

Two layers (per the user's "universal OR organizational" framing):
  • UNIVERSAL — curated, well-established software-engineering practices baked in
    here. Real, defensible, domain-tagged.
  • ORGANIZATIONAL — optional, loaded from ~/.sentigent/org_best_practices.json
    so a team can extend/override without code changes.

A ProfileReview (core/profile_review.py) checks which of these the operator's
profile + declared practices already embody (the GOOD), which are missing (the
GAPS → adoptable SUGGESTIONS), and — via the local LLM — which profile traits
work against a best practice (the BAD).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Practice:
    key: str
    domain: str          # testing | review | git | deploy | db | security | quality | process | safety
    statement: str       # the practice, phrased as something you'd declare
    rationale: str       # why it matters
    importance: str      # high | medium | low
    cadence: str = "always"   # always | commit | milestone | deploy | pr
    keywords: list[str] = field(default_factory=list)  # for deterministic coverage match

    def covered_by(self, text: str) -> bool:
        low = text.lower()
        return any(k.lower() in low for k in self.keywords)


# The universal benchmark. Kept tight and high-signal, not exhaustive.
UNIVERSAL: list[Practice] = [
    Practice("tests-before-commit", "testing",
             "Run the relevant tests before committing", "Catches regressions while context is fresh and cheap to fix",
             "high", "commit", ["test", "tests", "suite", "vitest", "pytest", "coverage"]),
    Practice("ci-gate", "testing",
             "Gate merges on a green CI run (typecheck + tests)", "Stops broken code reaching the shared branch",
             "high", "pr", ["ci", "continuous integration", "typecheck", "tsc", "lint gate", "green build"]),
    Practice("self-review-diff", "review",
             "Self-review the full diff before opening a PR", "You catch half your own bugs by reading the diff cold",
             "high", "pr", ["self-review", "review the diff", "review diff", "read the diff", "code review"]),
    Practice("peer-review-risky", "review",
             "Get a second pair of eyes on risky/security/data changes", "High-blast-radius changes deserve review",
             "medium", "pr", ["peer review", "second pair", "reviewer", "approval"]),
    Practice("atomic-commits", "git",
             "Make small, atomic commits with clear messages", "Easy to review, bisect, and revert",
             "medium", "commit", ["atomic commit", "small commit", "commit message", "clear message"]),
    Practice("no-force-push-shared", "git",
             "Never force-push a shared branch (main/master)", "Rewriting shared history loses teammates' work",
             "high", "always", ["force-push", "force push", "no-force", "never force"]),
    Practice("staging-before-prod", "deploy",
             "Validate in staging/preview before production", "Find deploy-time breakage off the critical path",
             "high", "deploy", ["staging", "preview deploy", "before prod", "before production"]),
    Practice("rollback-plan", "deploy",
             "Have a rollback path before a production deploy", "Recovery should not be invented mid-incident",
             "medium", "deploy", ["rollback", "revert deploy", "roll back"]),
    Practice("feature-flag-risky", "deploy",
             "Ship risky changes behind a feature flag", "Decouple deploy from release; kill instantly",
             "medium", "deploy", ["feature flag", "feature-flag", "flag", "kill switch"]),
    Practice("migrations-reviewed", "db",
             "Review and back up before destructive DB migrations", "Schema/data loss is often irreversible",
             "high", "deploy", ["migration", "alter table", "backup", "point-in-time", "pitr"]),
    Practice("no-prod-edits", "db",
             "Never hand-edit production data unattended", "One wrong WHERE clause is a very bad day",
             "high", "always", ["prod data", "production data", "manual edit", "no-prod-edit"]),
    Practice("no-secrets-in-code", "security",
             "Never commit secrets; load from a vault/env", "Leaked keys are forever; rotation is painful",
             "high", "always", ["secret", "api key", "credential", "vault", "doppler", "env var"]),
    Practice("validate-inputs", "security",
             "Validate and sanitize external inputs", "Untrusted input is the root of most vulns",
             "medium", "always", ["validate input", "sanitize", "zod", "schema validation"]),
    Practice("typed-no-any", "quality",
             "Prefer types; avoid escape hatches like `any`/`@ts-ignore`", "Types are the cheapest tests you have",
             "medium", "always", ["typescript", "no any", "typed", "strict types", "type safety"]),
    Practice("handle-errors", "quality",
             "Handle errors explicitly; no silent catches", "Swallowed errors hide real failures",
             "medium", "always", ["error handling", "try/catch", "fail-soft", "handle error", "error boundary"]),
    Practice("definition-of-done", "process",
             "Define done-criteria per task before starting", "You can't verify what you didn't define",
             "medium", "always", ["definition of done", "done criteria", "acceptance", "verify"]),
    Practice("incremental-over-bigbang", "process",
             "Prefer small incremental changes over big-bang rewrites", "Smaller diffs = smaller risk, faster feedback",
             "medium", "always", ["incremental", "small change", "atomic", "no rewrite", "ship small"]),
    Practice("confirm-irreversible", "safety",
             "Confirm before destructive/irreversible actions", "rm -rf, drop table, force-push deserve a pause",
             "high", "always", ["confirm", "irreversible", "destructive", "are you sure", "double-check"]),
]


def load_org(path: Optional[str] = None) -> list[Practice]:
    """Load optional org-level best practices from JSON. Missing file => []."""
    p = path or os.path.expanduser("~/.sentigent/org_best_practices.json")
    try:
        with open(p) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out: list[Practice] = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(Practice(
                key=str(d["key"]), domain=str(d.get("domain", "global")),
                statement=str(d["statement"]), rationale=str(d.get("rationale", "")),
                importance=str(d.get("importance", "medium")),
                cadence=str(d.get("cadence", "always")),
                keywords=[str(k) for k in d.get("keywords", [])],
            ))
        except (KeyError, TypeError):
            continue
    return out


def all_practices(include_org: bool = True) -> list[Practice]:
    return UNIVERSAL + (load_org() if include_org else [])
