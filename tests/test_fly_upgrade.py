"""Tests for the Fly-upgrade: diff-aware judge (Task 9) + self-repair retry (Task 10)."""
from sentigent.operator.gate import ProfileGate
from sentigent.operator.operate import _criteria_brief, _step_prompt, _loads_criteria
from sentigent.operator.plan import Plan, Step


def test_gate_prompt_includes_work():
    g = ProfileGate(profile={}, practices=[])
    p = g._prompt("Add field X", "low/normal",
                  work="diff --git a/x.py\n+ phase: str = ''")
    assert "phase: str" in p          # the ACTUAL change is in the judge's prompt
    assert "WORKER ACTUALLY DID" in p
    p2 = g._prompt("Add field X", "low/normal")   # back-compat: no work
    assert isinstance(p2, str) and "WORKER ACTUALLY DID" not in p2


def test_criteria_brief_renders_each_key():
    brief = _criteria_brief({
        "test_cmd": "pytest x", "build_cmd": "npm run build",
        "files_exist": ["a.tsx"], "grep": {"pattern": "Foo", "path": "a.ts"},
        "diff_nonempty": True,
    })
    assert "pytest x" in brief and "npm run build" in brief
    assert "a.tsx" in brief and "Foo" in brief and "real code change" in brief
    assert _criteria_brief({}) == ""


def test_step_prompt_carries_phase_and_acceptance_criteria():
    plan = Plan(goal="Refactor dashboard", steps=[])
    step = Step(idx=1, description="Harmonize header", phase="Phase 1: tokens",
                done_criteria={"build_cmd": "npm run build", "files_exist": ["a.tsx"]})
    out = _step_prompt(plan, step, prior=[])
    assert "Phase 1: tokens" in out
    assert "npm run build" in out and "a.tsx" in out
    assert "do this step (and only this step): Harmonize header" in out
    assert "DONE only when" in out


def test_loads_criteria_handles_json_dict_and_garbage():
    assert _loads_criteria('{"build_cmd": "x"}') == {"build_cmd": "x"}
    assert _loads_criteria({"test_cmd": "y"}) == {"test_cmd": "y"}
    assert _loads_criteria("not json") == {}
    assert _loads_criteria(None) == {}
    assert _loads_criteria("") == {}
