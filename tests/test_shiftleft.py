"""Shift-left test gate: detection + that the Verifier actually runs the test_cmd."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from sentigent.operator.shiftleft import detect_test_command, ensure_test_criterion
from sentigent.operator.verifier import Verifier


def _tmp(files: dict, dirs: list[str] | None = None) -> str:
    d = tempfile.mkdtemp()
    for name in (dirs or []):
        os.makedirs(os.path.join(d, name), exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    return d


def test_detect_node():
    d = _tmp({"package.json": json.dumps({"scripts": {"test": "jest"}})})
    assert detect_test_command(d) == "npm test --silent"


def test_detect_node_skips_npm_placeholder():
    d = _tmp({"package.json": json.dumps(
        {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})})
    assert detect_test_command(d) is None


def test_detect_python_and_empty():
    assert detect_test_command(_tmp({"pyproject.toml": "[tool.pytest]"})) == "pytest -q"
    assert detect_test_command(_tmp({}, dirs=["tests"])) == "pytest -q"
    assert detect_test_command(_tmp({"README.md": "hi"})) is None


def test_python_requires_a_real_pytest_signal():
    # A pyproject.toml / setup.cfg that exists only for lint/build config (no tests) must NOT
    # yield a test command — gating on it would fail a genuinely-done step (D-016 sweep).
    assert detect_test_command(_tmp({"pyproject.toml": "[tool.black]\nline-length = 100\n"})) is None
    assert detect_test_command(_tmp({"setup.cfg": "[metadata]\nname = x\n"})) is None
    # But a real pytest signal anywhere is honored.
    assert detect_test_command(_tmp({"pyproject.toml": "[tool.pytest.ini_options]\n"})) == "pytest -q"
    assert detect_test_command(_tmp({"tox.ini": "[testenv]\ncommands = pytest\n"})) == "pytest -q"
    assert detect_test_command(_tmp({"pytest.ini": "[pytest]\n"})) == "pytest -q"


def test_ensure_does_not_override_explicit():
    d = _tmp({"pyproject.toml": "[tool.pytest.ini_options]"})
    assert ensure_test_criterion({"test_cmd": "make ci"}, d)["test_cmd"] == "make ci"
    assert ensure_test_criterion({}, d)["test_cmd"] == "pytest -q"


def test_verifier_actually_runs_the_test_cmd():
    # The shift-left gate is only real if a failing test blocks "done".
    d = _tmp({})
    assert Verifier(d, timeout=10).verify({"test_cmd": "true"}).done is True
    res = Verifier(d, timeout=10).verify({"test_cmd": "false"})
    assert res.done is False
    assert any(c.kind == "test" and not c.passed for c in res.checks)
