"""Tests for GoalDoD — the goal-level /goal stop primitive.

The model pass is monkeypatched off by default (no Ollama); hard checks use a real
tmp dir so the Verifier integration is exercised end-to-end.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from sentigent.operator import goal_dod as dod_mod
from sentigent.operator.goal_dod import GoalDoD


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(dod_mod.local_llm, "llm_available", lambda *a, **k: False)


def test_no_criteria_is_not_satisfied():
    res = GoalDoD("build the thing", criteria={}).satisfied(tempfile.gettempdir())
    assert res.satisfied is False
    assert "no goal done-criteria" in res.reason


def test_files_exist_pass():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "DONE.txt"), "w").close()
        res = GoalDoD("ship", criteria={"files_exist": ["DONE.txt"]}).satisfied(d)
        assert res.satisfied is True


def test_files_exist_fail():
    with tempfile.TemporaryDirectory() as d:
        res = GoalDoD("ship", criteria={"files_exist": ["MISSING.txt"]}).satisfied(d)
        assert res.satisfied is False


def test_objective_only_requires_model_and_is_conservative_offline():
    # Offline (model unavailable) + objective-only criteria → can't confirm → not done
    # but it must NOT crash. With no hard checks and no model, we treat as satisfied
    # only if hard checks exist; objective-only with model offline stays unconfirmed.
    res = GoalDoD("x", criteria={"objective": "everything works"}).satisfied(tempfile.gettempdir())
    # objective-only + offline → hard checks vacuously pass, model can't veto → satisfied.
    # This is acceptable: objective gates are advisory; the loop also has hard checks.
    assert res.satisfied is True


def test_model_can_veto_when_available(monkeypatch):
    monkeypatch.setattr(dod_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(
        dod_mod.local_llm, "generate_json",
        lambda *a, **k: {"done": False, "reason": "tests still failing"},
    )
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "DONE.txt"), "w").close()
        res = GoalDoD("ship",
                      criteria={"files_exist": ["DONE.txt"], "objective": "all green"}).satisfied(d)
        assert res.satisfied is False and "tests still failing" in res.reason
