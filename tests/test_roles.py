"""Tests for sentigent/operator/roles.py — maker/checker + explorer/implementer/
verifier role scaffolds (roadmap X1). Pure string logic, fully deterministic.
"""
import pytest

from sentigent.operator import roles as R


def test_role_constants_are_distinct_nonempty_strings():
    for c in (R.EXPLORER, R.IMPLEMENTER, R.VERIFIER):
        assert isinstance(c, str) and c.strip()
    assert len({R.EXPLORER, R.IMPLEMENTER, R.VERIFIER}) == 3


def test_role_prompt_prepends_prefix():
    out = R.role_prompt(R.EXPLORER, "read the parser")
    assert out.endswith("read the parser")
    assert out.startswith(R.EXPLORER)
    assert "read the parser" in out


def test_role_prompt_each_known_role():
    step = "do the thing"
    for role in (R.EXPLORER, R.IMPLEMENTER, R.VERIFIER):
        out = R.role_prompt(role, step)
        assert role in out
        assert step in out


def test_role_prompt_unknown_role_raises():
    with pytest.raises(ValueError):
        R.role_prompt("janitor", "sweep up")


def test_maker_checker_returns_two_steps():
    steps = R.maker_checker("add the feature")
    assert isinstance(steps, list)
    assert len(steps) == 2


def test_maker_checker_tags_implementer_then_verifier():
    impl, verify = R.maker_checker("add the feature")
    assert impl.startswith(R.IMPLEMENTER)
    assert verify.startswith(R.VERIFIER)
    assert "add the feature" in impl
    assert "add the feature" in verify


def test_maker_checker_explorer_not_used():
    # maker/checker is the 2-step separation: make then prove. No explorer step.
    impl, verify = R.maker_checker("ship it")
    assert not impl.startswith(R.EXPLORER)
    assert not verify.startswith(R.EXPLORER)
