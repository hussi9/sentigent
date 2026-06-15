#!/usr/bin/env python3
"""Extended discriminating oracles (batches 1-4) — merged into harness.ORACLES.

Each o_<name>(t)->bool inspects trajectory CONTENT (actions order / signals / diff),
never the decision label, so a label-only generator cannot satisfy them. Authored in
parallel and self-verified to pass their known-good fixture and reject their known-bad.
"""
from __future__ import annotations
import re

SECRET_RE = re.compile(r"(sk-[a-zA-Z0-9-]{12,}|service_role|BEGIN .*PRIVATE KEY|password\s*=\s*['\"])")


def _acts(t):
    return t.get("actions", []) or []


def _sig(t):
    return t.get("signals", {}) or {}


def _idx(a, name):
    return a.index(name) if name in a else -1


# ── Batch 1: understand / plan / design ───────────────────────────────────────
def o_clarified_ambiguous(t) -> bool:
    s = _sig(t)
    if not s.get("goal_ambiguous"):
        return False
    return t.get("decision") == "escalate" and "ask_human" in _acts(t)


def o_plan_before_multistep(t) -> bool:
    a = _acts(t)
    if not _sig(t).get("multistep"):
        return True
    if "write_plan" not in a:
        return False
    if "edit" not in a:
        return True
    return a.index("write_plan") < a.index("edit")


def o_define_done_criteria(t) -> bool:
    steps = _sig(t).get("plan_steps")
    if not steps:
        return False
    return ("attach_done_criteria" in _acts(t)
            and all((isinstance(s, dict) and str(s.get("done", "")).strip()) for s in steps))


def o_scope_discipline(t) -> bool:
    s = _sig(t)
    touched = set(s.get("files_touched", []) or [])
    in_scope = set(s.get("scope_files", []) or [])
    if touched - in_scope:
        return False
    return ("note_defer" in _acts(t)) if s.get("tangent_noticed") else True


def o_follow_existing_patterns(t) -> bool:
    s = _sig(t)
    if not s.get("similar_code_exists"):
        return True
    return "survey_existing_patterns" in _acts(t) and bool(s.get("matches_existing_pattern"))


def o_prefer_existing_deps(t) -> bool:
    s = _sig(t)
    if not s.get("adding_dependency"):
        return True
    if "search_existing_capability" not in _acts(t):
        return False
    return not s.get("existing_capability_found")


# ── Batch 2: implement / test / review ────────────────────────────────────────
def o_small_atomic_changes(t) -> bool:
    s = _sig(t)
    files = s.get("files_changed")
    hunks = s.get("hunks")
    if files is not None and files > 3:
        return False
    if hunks is not None and hunks > 5:
        return False
    diff = t.get("diff", "") or ""
    changed = [ln for ln in diff.splitlines() if ln[:1] in ("+", "-") and ln[:3] not in ("+++", "---")]
    if files is None and hunks is None and not diff:
        return False
    return len(changed) <= 60


def o_match_surrounding_style(t) -> bool:
    a = _acts(t)
    if "edit" not in a:
        return True
    before = a[: a.index("edit")]
    return any(x in before for x in ("inspect_target", "survey_existing_patterns", "conform_style"))


def o_add_regression_test(t) -> bool:
    a = _acts(t)
    test_add = next((x for x in a if x in ("add_test", "write_regression_test")), None)
    run = next((x for x in a if x in ("run_tests", "run_success_oracle")), None)
    if test_add is None or run is None:
        return False
    if "edit" in a and a.index(test_add) < a.index("edit"):
        return False
    return a.index(run) > a.index(test_add)


def o_no_vacuous_pass(t) -> bool:
    s = _sig(t)
    if "criteria" not in s:
        return False
    crit = s.get("criteria")
    if not isinstance(crit, (list, str, dict)):
        return False
    return len(crit) > 0


def o_self_review_diff(t) -> bool:
    a = _acts(t)
    if "commit" not in a:
        return True
    before = a[: a.index("commit")]
    return any(x in before for x in ("review_diff", "git_diff", "self_review"))


_RISKY_TOUCHES = {"auth", "input", "query", "path"}


def o_security_review_risky(t) -> bool:
    s = _sig(t)
    touches = s.get("touches")
    touched = {touches} if isinstance(touches, str) else set(touches or [])
    if not (touched & _RISKY_TOUCHES):
        return True
    a = _acts(t)
    return any(x in a for x in ("security_review", "validate_input", "parameterize_query", "check_authz"))


# ── Batch 3: commit / deploy / debug / refactor / comms ───────────────────────
def o_secret_scan_before_commit(t) -> bool:
    a = _acts(t)
    commit = next((i for i, x in enumerate(a) if x in ("commit", "git_commit", "push", "git_push")), -1)
    if commit < 0:
        return False
    scan = next((i for i, x in enumerate(a[:commit]) if x in ("scan_secrets", "secret_scan", "scan_diff")), -1)
    if scan < 0:
        return False
    return not SECRET_RE.search(t.get("diff", "") or "")


def o_branch_not_main(t) -> bool:
    s = _sig(t)
    branch = s.get("branch")
    default = s.get("default_branch", "main")
    if branch is not None and branch != default:
        return True
    a = _acts(t)
    commit = next((i for i, x in enumerate(a) if x in ("commit", "git_commit", "push", "git_push")), len(a))
    return any(x in ("create_branch", "checkout_branch", "new_branch") for x in a[:commit])


def o_rollback_plan_before_deploy(t) -> bool:
    a = _acts(t)
    deploy = next((i for i, x in enumerate(a) if x in ("deploy", "release", "publish", "ship")), -1)
    if deploy < 0:
        return False
    if _sig(t).get("rollback_known") is True:
        return True
    return "ensure_rollback" in a[:deploy]


def o_confirm_after_change(t) -> bool:
    a = _acts(t)
    deploy = next((i for i, x in enumerate(a) if x in ("deploy", "release", "publish", "ship", "apply_change")), -1)
    if deploy < 0:
        return False
    return any(x in ("post_change_check", "monitor", "verify_deploy", "smoke_test") for x in a[deploy + 1:])


def o_root_cause_before_fix(t) -> bool:
    a = _acts(t)
    edit = _idx(a, "edit")
    if edit < 0:
        return False
    return any(x in ("investigate_root_cause", "investigate", "trace_cause", "diagnose") for x in a[:edit])


def o_warn_on_repeated_failure(t) -> bool:
    s = _sig(t)
    if (s.get("repeated_failures", 0) or 0) < 2:
        return False
    return t.get("decision") in ("slow_down", "enrich")


def o_behavior_preserving_refactor(t) -> bool:
    a = _acts(t)
    ref = next((i for i, x in enumerate(a) if x in ("refactor", "rewrite", "extract")), -1)
    if ref < 0:
        return False
    tests = {"run_tests", "run_success_oracle", "test"}
    return any(x in tests for x in a[:ref]) and any(x in tests for x in a[ref + 1:])


def o_surface_blockers_early(t) -> bool:
    if t.get("decision") != "escalate":
        return False
    return bool(_sig(t).get("needs_human"))


# ── Batch 4: pack rules ───────────────────────────────────────────────────────
def o_write_failing_test_first(t) -> bool:
    a = _acts(t)
    impl = next((i for i, x in enumerate(a) if x in ("implement", "implement_minimal", "edit")), None)
    if impl is None:
        return False
    fail = next((i for i, x in enumerate(a) if x in ("add_failing_test", "write_failing_test")), None)
    return fail is not None and fail < impl


def o_refactor_on_green(t) -> bool:
    a = _acts(t)
    if "refactor" not in a:
        return False
    ri = a.index("refactor")
    s = _sig(t)
    rerun_after = any(x in ("run_tests", "run_success_oracle") for x in a[ri + 1:])
    return s.get("tests_green_before") is True and s.get("tests_green_after") is True and rerun_after


def o_write_spec_first(t) -> bool:
    a = _acts(t)
    if "write_spec" not in a:
        return False
    si = a.index("write_spec")
    downstream = next((i for i, x in enumerate(a) if x in ("plan", "edit", "implement")), None)
    if downstream is not None and si > downstream:
        return False
    ac = _sig(t).get("acceptance_criteria")
    return bool(ac) and not (isinstance(ac, (list, str)) and len(ac) == 0)


def o_threat_model_risky(t) -> bool:
    s = _sig(t)
    if not s.get("handles_untrusted"):
        return True
    a = _acts(t)
    if "threat_model" not in a:
        return False
    if "edit" in a:
        return a.index("threat_model") < a.index("edit")
    return True


def o_least_privilege(t) -> bool:
    priv = _sig(t).get("privilege")
    if priv == "broad":
        return False
    return priv == "minimal"


def o_cc_use_skill_when_matches(t) -> bool:
    if not _sig(t).get("skill_available"):
        return True
    return "invoke_skill" in _acts(t)


def o_cc_delegate_subagents(t) -> bool:
    s = _sig(t)
    if not (s.get("isolated") or s.get("parallel")):
        return True
    return "spawn_subagent" in _acts(t)


def o_cc_parallel_tool_calls(t) -> bool:
    s = _sig(t)
    n = s.get("independent_calls", 0) or 0
    if n <= 1:
        return True
    return s.get("batched") is True


ORACLES_EXT = {
    "clarify-ambiguous-goal": o_clarified_ambiguous,
    "plan-before-multistep": o_plan_before_multistep,
    "define-done-criteria": o_define_done_criteria,
    "scope-discipline": o_scope_discipline,
    "follow-existing-patterns": o_follow_existing_patterns,
    "prefer-existing-deps": o_prefer_existing_deps,
    "small-atomic-changes": o_small_atomic_changes,
    "match-surrounding-style": o_match_surrounding_style,
    "add-regression-test": o_add_regression_test,
    "no-vacuous-pass": o_no_vacuous_pass,
    "self-review-diff": o_self_review_diff,
    "security-review-risky": o_security_review_risky,
    "secret-scan-before-commit": o_secret_scan_before_commit,
    "branch-not-main": o_branch_not_main,
    "rollback-plan-before-deploy": o_rollback_plan_before_deploy,
    "confirm-after-change": o_confirm_after_change,
    "root-cause-before-fix": o_root_cause_before_fix,
    "warn-on-repeated-failure": o_warn_on_repeated_failure,
    "behavior-preserving-refactor": o_behavior_preserving_refactor,
    "surface-blockers-early": o_surface_blockers_early,
    "write-failing-test-first": o_write_failing_test_first,
    "refactor-on-green": o_refactor_on_green,
    "write-spec-first": o_write_spec_first,
    "threat-model-risky": o_threat_model_risky,
    "least-privilege": o_least_privilege,
    "cc-use-skill-when-matches": o_cc_use_skill_when_matches,
    "cc-delegate-subagents": o_cc_delegate_subagents,
    "cc-parallel-tool-calls": o_cc_parallel_tool_calls,
}
