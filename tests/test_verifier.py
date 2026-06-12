"""Tests for the Operator Verifier (B4 anti-hallucination gate)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

from sentigent.operator.verifier import CheckResult, Verifier, VerifyResult


@pytest.fixture
def workdir():
    d = tempfile.mkdtemp(prefix="verifier_test_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _init_git_repo(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


# -- test_cmd / build_cmd -------------------------------------------------

def test_test_cmd_exit_zero_passes(workdir):
    res = Verifier(workdir).verify({"test_cmd": "exit 0"})
    assert isinstance(res, VerifyResult)
    assert res.done is True
    assert len(res.checks) == 1
    assert res.checks[0].kind == "test"
    assert res.checks[0].passed is True


def test_test_cmd_exit_one_fails(workdir):
    res = Verifier(workdir).verify({"test_cmd": "exit 1"})
    assert res.done is False
    assert res.checks[0].kind == "test"
    assert res.checks[0].passed is False


def test_build_cmd_kind(workdir):
    res = Verifier(workdir).verify({"build_cmd": "true"})
    assert res.done is True
    assert res.checks[0].kind == "build"


def test_command_timeout_fails_no_raise(workdir):
    # timeout=0.001 on sleep 1 -> must fail the check, never raise.
    res = Verifier(workdir, timeout=0.001).verify({"test_cmd": "sleep 1"})
    assert res.done is False
    assert res.checks[0].passed is False
    assert "timed out" in res.checks[0].detail


# -- files_exist ----------------------------------------------------------

def test_files_exist_hit(workdir):
    open(os.path.join(workdir, "a.txt"), "w").close()
    os.makedirs(os.path.join(workdir, "sub"))
    open(os.path.join(workdir, "sub", "b.txt"), "w").close()
    res = Verifier(workdir).verify({"files_exist": ["a.txt", "sub/b.txt"]})
    assert res.done is True
    assert res.checks[0].kind == "files_exist"
    assert res.checks[0].passed is True


def test_files_exist_miss(workdir):
    open(os.path.join(workdir, "a.txt"), "w").close()
    res = Verifier(workdir).verify({"files_exist": ["a.txt", "missing.txt"]})
    assert res.done is False
    assert res.checks[0].passed is False
    assert "missing.txt" in res.checks[0].detail


# -- diff_nonempty --------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_diff_nonempty_no_changes_fails(workdir):
    _init_git_repo(workdir)
    res = Verifier(workdir).verify({"diff_nonempty": True})
    assert res.done is False
    assert res.checks[0].kind == "diff_nonempty"
    assert res.checks[0].passed is False


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_diff_nonempty_after_staging_passes(workdir):
    _init_git_repo(workdir)
    # Commit a baseline so a staged modification shows in `git diff`.
    f = os.path.join(workdir, "file.txt")
    with open(f, "w") as fh:
        fh.write("original\n")
    subprocess.run(["git", "add", "file.txt"], cwd=workdir, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=workdir, check=True)
    # Modify + stage -> git diff --stat must now report the change.
    with open(f, "w") as fh:
        fh.write("changed\n")
    subprocess.run(["git", "add", "file.txt"], cwd=workdir, check=True)
    res = Verifier(workdir).verify({"diff_nonempty": True})
    assert res.done is True
    assert res.checks[0].passed is True


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_diff_nonempty_untracked_new_file_passes(workdir):
    # Regression: a fresh `claude -p` step creates a brand-NEW untracked file.
    # `git diff`/`--cached` are blind to untracked files, so the old check
    # reported "nothing happened" and failed a step that really did work.
    # The check now decides on `git status --porcelain`, which sees untracked.
    _init_git_repo(workdir)
    with open(os.path.join(workdir, "hello.txt"), "w") as fh:
        fh.write("hello\n")  # NOT staged — purely untracked, like a worker write
    res = Verifier(workdir).verify({"diff_nonempty": True})
    assert res.done is True
    assert res.checks[0].kind == "diff_nonempty"
    assert res.checks[0].passed is True


# -- grep -----------------------------------------------------------------

def test_grep_hit(workdir):
    p = os.path.join(workdir, "code.py")
    with open(p, "w") as fh:
        fh.write("def hello():\n    return 42\n")
    res = Verifier(workdir).verify({"grep": {"pattern": r"def\s+hello", "path": "code.py"}})
    assert res.done is True
    assert res.checks[0].kind == "grep"
    assert res.checks[0].passed is True


def test_grep_miss(workdir):
    p = os.path.join(workdir, "code.py")
    with open(p, "w") as fh:
        fh.write("nothing here\n")
    res = Verifier(workdir).verify({"grep": {"pattern": r"def\s+hello", "path": "code.py"}})
    assert res.done is False
    assert res.checks[0].passed is False


def test_grep_missing_file_fails(workdir):
    res = Verifier(workdir).verify({"grep": {"pattern": "x", "path": "nope.py"}})
    assert res.done is False
    assert res.checks[0].passed is False
    assert "not found" in res.checks[0].detail


# -- empty criteria -------------------------------------------------------

def test_empty_criteria_not_done(workdir):
    res = Verifier(workdir).verify({})
    assert res.done is False
    assert res.reason == "no done-criteria"
    assert len(res.checks) == 1
    assert res.checks[0].kind == "no_criteria"
    assert res.checks[0].passed is False


# -- AND semantics + serialization ---------------------------------------

def test_and_semantics_one_fail_blocks_done(workdir):
    open(os.path.join(workdir, "a.txt"), "w").close()
    res = Verifier(workdir).verify({
        "test_cmd": "exit 0",
        "files_exist": ["a.txt"],
        "grep": {"pattern": "x", "path": "missing.py"},
    })
    assert res.done is False
    assert sum(1 for c in res.checks if c.passed) == 2
    assert sum(1 for c in res.checks if not c.passed) == 1


def test_to_dict_shape(workdir):
    res = Verifier(workdir).verify({"test_cmd": "exit 0"})
    d = res.to_dict()
    assert d["done"] is True
    assert isinstance(d["checks"], list)
    assert d["checks"][0]["kind"] == "test"
    assert set(d["checks"][0].keys()) == {"kind", "passed", "detail"}
    assert isinstance(CheckResult("test", True, "ok").to_dict(), dict)
