"""Tests for the PURE functions of sentigent/operator/loop_driver.py.

No network, no `claude`, no real subprocess — only the deterministic helpers
`_mk_step` (step normalization) and `_step_gate` (per-step vs global done-criteria).
"""
from sentigent.operator import loop_driver as L


# ── _mk_step ───────────────────────────────────────────────────────────────────
def test_mk_step_bare_string_has_no_verify_key():
    step = L._mk_step(0, "write the parser")
    assert step["i"] == 0
    assert step["text"] == "write the parser"
    assert step["status"] == "pending"
    assert step["attempts"] == 0
    assert "verify" not in step


def test_mk_step_bare_string_coerces_non_string():
    step = L._mk_step(2, 123)
    assert step["text"] == "123"
    assert step["i"] == 2
    assert "verify" not in step


def test_mk_step_dict_with_verify_keeps_explicit_key():
    step = L._mk_step(1, {"text": "run the tests", "verify": "pytest -q"})
    assert step["text"] == "run the tests"
    assert "verify" in step
    assert step["verify"] == "pytest -q"


def test_mk_step_dict_with_empty_verify_keeps_empty_key():
    step = L._mk_step(3, {"text": "draft only", "verify": ""})
    assert step["text"] == "draft only"
    assert "verify" in step
    assert step["verify"] == ""


def test_mk_step_dict_without_verify_has_no_verify_key():
    step = L._mk_step(4, {"text": "no gate here"})
    assert step["text"] == "no gate here"
    assert "verify" not in step


def test_mk_step_dict_coerces_verify_to_string():
    step = L._mk_step(5, {"text": "x", "verify": 0})
    assert step["verify"] == "0"
    assert isinstance(step["verify"], str)


# ── _step_gate ───────────────────────────────────────────────────────────────────
def test_step_gate_uses_step_verify_when_present():
    state = {"verify_cmd": "make check"}
    step = {"verify": "pytest -q"}
    assert L._step_gate(state, step) == "pytest -q"


def test_step_gate_empty_step_verify_overrides_global():
    state = {"verify_cmd": "make check"}
    step = {"verify": ""}
    # an explicit empty verify means "trust this step" — it must win over the global
    assert L._step_gate(state, step) == ""


def test_step_gate_falls_back_to_global_verify_cmd():
    state = {"verify_cmd": "make check"}
    step = {"text": "no per-step gate"}
    assert L._step_gate(state, step) == "make check"


def test_step_gate_falls_back_to_empty_when_no_global():
    state = {}
    step = {"text": "no gate anywhere"}
    assert L._step_gate(state, step) == ""


def test_step_gate_integrates_with_mk_step():
    state = {"verify_cmd": "make check"}
    bare = L._mk_step(0, "code it")
    gated = L._mk_step(1, {"text": "test it", "verify": "pytest -q"})
    trusted = L._mk_step(2, {"text": "draft", "verify": ""})
    assert L._step_gate(state, bare) == "make check"   # falls back
    assert L._step_gate(state, gated) == "pytest -q"   # own gate
    assert L._step_gate(state, trusted) == ""          # explicit empty wins


# ── state lifecycle (start → load round-trip) ───────────────────────────────────
def test_start_then_load_round_trips_state(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)  # no real ~/.sentigent touched
    state = L.start("ship the thing", ["code it", {"text": "test it", "verify": "pytest -q"}],
                    stamp=123.0)
    loop_id = state["loop_id"]

    loaded = L.load(loop_id)
    assert loaded["status"] == "running"
    assert loaded["cursor"] == 0
    assert loaded["goal"] == "ship the thing"
    assert loaded == state  # JSON round-trip is faithful

    # steps were normalized via _mk_step
    assert len(loaded["steps"]) == 2
    bare, gated = loaded["steps"]
    assert bare["text"] == "code it"
    assert bare["status"] == "pending"
    assert bare["attempts"] == 0
    assert "verify" not in bare
    assert gated["text"] == "test it"
    assert gated["verify"] == "pytest -q"


def test_load_missing_loop_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    import pytest
    with pytest.raises(SystemExit):
        L.load("loop_deadbeef")  # valid format, just not on disk


# ── metrics (FAP and friends) ───────────────────────────────────────────────────
def test_metrics_two_verified_one_pending():
    state = {
        "steps": [
            {"i": 0, "status": "done", "verified": True, "asked": False},
            {"i": 1, "status": "done", "verified": True, "asked": False},
            {"i": 2, "status": "pending", "verified": None, "asked": False},
        ],
        "asks": 0,
        "clone_resolves": 0,
    }
    m = L.metrics(state)
    assert m["FAP"] == round(2 / 3, 3)
    assert m["fidelity"] == 1.0
    assert m["verified_steps"] == "2/3"
    assert m["faithful_streak"] == 2


# ── _build_prompt ────────────────────────────────────────────────────────────────
def test_build_prompt_includes_goal_step_and_done_criteria():
    state = {
        "goal": "ship the parser",
        "verify_cmd": "make check",
        "steps": [
            {"i": 0, "status": "done", "text": "scaffold the module"},
            {"i": 1, "status": "pending", "text": "write the tokenizer"},
        ],
    }
    step = {"text": "write the tokenizer", "verify": "pytest -q", "last_error": ""}
    prompt = L._build_prompt(state, step)

    # the GOAL text is present
    assert "ship the parser" in prompt
    # the step text is present
    assert "write the tokenizer" in prompt
    # the done-criteria line carries the step's own gate command
    assert "This step is DONE when this command passes: `pytest -q`" in prompt


def test_build_prompt_done_criteria_uses_global_gate_when_no_step_verify():
    state = {
        "goal": "g",
        "verify_cmd": "make check",
        "steps": [{"i": 0, "status": "pending", "text": "do it"}],
    }
    step = {"text": "do it", "last_error": ""}  # no per-step verify
    prompt = L._build_prompt(state, step)
    assert "This step is DONE when this command passes: `make check`" in prompt


def test_build_prompt_omits_done_criteria_when_gate_empty():
    state = {
        "goal": "g",
        "steps": [{"i": 0, "status": "pending", "text": "draft only"}],
    }
    step = {"text": "draft only", "verify": "", "last_error": ""}  # explicit empty gate
    prompt = L._build_prompt(state, step)
    assert "This step is DONE when this command passes" not in prompt


def test_build_prompt_includes_last_error_when_set():
    state = {
        "goal": "g",
        "verify_cmd": "pytest -q",
        "steps": [{"i": 0, "status": "pending", "text": "fix the bug"}],
    }
    step = {"text": "fix the bug", "last_error": "AssertionError: expected 3 got 4"}
    prompt = L._build_prompt(state, step)
    assert "AssertionError: expected 3 got 4" in prompt
    assert "FAILED VERIFICATION" in prompt


def test_build_prompt_omits_error_block_when_no_last_error():
    state = {
        "goal": "g",
        "verify_cmd": "pytest -q",
        "steps": [{"i": 0, "status": "pending", "text": "first try"}],
    }
    step = {"text": "first try", "last_error": ""}
    prompt = L._build_prompt(state, step)
    assert "FAILED VERIFICATION" not in prompt
