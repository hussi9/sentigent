from sentigent.operator.plan import Step, Plan, parse_plan, _parse_criteria


def test_step_has_new_fields():
    s = Step(idx=1, description="do thing")
    assert s.phase == ""
    assert s.done_criteria == {}


def test_parse_criteria_verify_and_files():
    desc, crit = _parse_criteria("Add X || verify: pytest tests/test_x.py || files: a.py, b.py")
    assert desc == "Add X"
    assert crit == {"test_cmd": "pytest tests/test_x.py", "files_exist": ["a.py", "b.py"]}


def test_parse_criteria_build_grep_diff():
    desc, crit = _parse_criteria("Ship || build: npm run build || grep: Foo @ src/a.ts || diff")
    assert desc == "Ship"
    assert crit["build_cmd"] == "npm run build"
    assert crit["grep"] == {"pattern": "Foo", "path": "src/a.ts"}
    assert crit["diff_nonempty"] is True


def test_parse_criteria_none():
    desc, crit = _parse_criteria("plain task with no criteria")
    assert desc == "plain task with no criteria"
    assert crit == {}


PLAN_MD = """# Refactor the dashboard

## Phase 1: tokens
- [ ] Harmonize header || files: app/page.tsx
- [x] Already done thing

## Phase 2: verify
1. Run build || build: npm run build
"""


def test_parse_plan_phases_and_criteria():
    plan = parse_plan(PLAN_MD)
    assert plan.goal == "Refactor the dashboard"
    assert len(plan.steps) == 3
    s1, s2, s3 = plan.steps
    assert s1.description == "Harmonize header"
    assert s1.phase == "Phase 1: tokens"
    assert s1.done_criteria == {"files_exist": ["app/page.tsx"]}
    assert s2.done is True
    assert s2.phase == "Phase 1: tokens"
    assert s3.description == "Run build"
    assert s3.phase == "Phase 2: verify"
    assert s3.done_criteria == {"build_cmd": "npm run build"}
