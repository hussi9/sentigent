"""Tests for WorktreeManager (C4) — real temp git repos, fail-soft on non-git dirs.

These tests spin up an actual git repo with tempfile + subprocess so we exercise the
real `git worktree` machinery (no mocks). If `git` isn't on PATH the whole module is
skipped gracefully.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

from sentigent.operator.worktree import WorktreeInfo, WorktreeManager

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available on PATH"
)


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: str) -> None:
    """Initialize a git repo with identity set and one initial commit."""
    _git(["init"], cwd=path)
    # Set identity locally so commits work without global config.
    _git(["config", "user.email", "operator@sentigent.local"], cwd=path)
    _git(["config", "user.name", "Sentigent Operator"], cwd=path)
    readme = os.path.join(path, "README.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write("# fixture repo\n")
    _git(["add", "-A"], cwd=path)
    _git(["-c", "commit.gpgsign=false", "commit", "-m", "initial"], cwd=path)


@pytest.fixture
def repo():
    d = tempfile.mkdtemp(prefix="sentigent-wt-repo-")
    try:
        _init_repo(d)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- create -----------------------------------------------------------------


def test_create_returns_real_worktree(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("abc123")

    assert info.created is True
    assert info.branch == "sentigent/run-abc123"
    assert os.path.isabs(info.path)
    assert os.path.isdir(info.path)
    assert len(info.base_sha) >= 7

    # It is genuinely a git worktree: .git here is a file pointing at the parent repo.
    dotgit = os.path.join(info.path, ".git")
    assert os.path.exists(dotgit)
    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=info.path,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "true"

    # The branch is checked out in the worktree.
    branch_proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=info.path,
        capture_output=True,
        text=True,
    )
    assert branch_proc.stdout.strip() == "sentigent/run-abc123"

    mgr.remove(info)


def test_create_dir_location_under_convention(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("loc1")
    expected = os.path.join(repo, ".sentigent-worktrees", "run-loc1")
    assert os.path.abspath(info.path) == os.path.abspath(expected)
    mgr.remove(info)


def test_create_on_non_git_dir_returns_not_created():
    d = tempfile.mkdtemp(prefix="sentigent-wt-nogit-")
    try:
        mgr = WorktreeManager(d)
        info = mgr.create("x")
        assert info.created is False
        assert info.base_sha == ""
        # No worktree dir should have been created.
        assert not os.path.isdir(os.path.join(d, ".sentigent-worktrees", "run-x"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- checkpoint -------------------------------------------------------------


def test_checkpoint_returns_sha_on_changes(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("ck1")
    try:
        newfile = os.path.join(info.path, "feature.txt")
        with open(newfile, "w", encoding="utf-8") as fh:
            fh.write("operator change\n")

        sha = mgr.checkpoint(info, "operator: add feature")
        assert sha is not None
        assert len(sha) >= 7

        # HEAD in the worktree now points at the checkpoint, distinct from base.
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=info.path,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == sha
        assert sha != info.base_sha
    finally:
        mgr.remove(info)


def test_checkpoint_returns_none_when_nothing_to_commit(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("ck2")
    try:
        assert mgr.checkpoint(info, "no-op") is None
    finally:
        mgr.remove(info)


def test_checkpoint_on_failed_info_is_none():
    bad = WorktreeInfo(path="/nonexistent/path", branch="b", base_sha="", created=False)
    mgr = WorktreeManager("/tmp")
    assert mgr.checkpoint(bad, "msg") is None


# --- diff -------------------------------------------------------------------


def test_diff_reflects_working_changes(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("df1")
    try:
        f = os.path.join(info.path, "working.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("uncommitted line\n")

        d = mgr.diff(info)
        assert "working.txt" in d
        assert "uncommitted line" in d
    finally:
        mgr.remove(info)


def test_diff_reflects_committed_changes(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("df2")
    try:
        f = os.path.join(info.path, "committed.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("committed line\n")
        mgr.checkpoint(info, "checkpoint")

        d = mgr.diff(info)
        assert "committed.txt" in d
        assert "committed line" in d
    finally:
        mgr.remove(info)


def test_diff_empty_on_failed_info():
    bad = WorktreeInfo(path="/nonexistent", branch="b", base_sha="", created=False)
    mgr = WorktreeManager("/tmp")
    assert mgr.diff(bad) == ""


# --- rollback ---------------------------------------------------------------


def test_rollback_resets_to_base(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("rb1")
    try:
        f = os.path.join(info.path, "tracked.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("v1\n")
        mgr.checkpoint(info, "cp")

        # Now HEAD is ahead of base; rollback should bring us back.
        assert mgr.rollback(info) is True
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=info.path,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == info.base_sha
    finally:
        mgr.remove(info)


def test_rollback_false_on_failed_info():
    bad = WorktreeInfo(path="/nonexistent", branch="b", base_sha="", created=False)
    mgr = WorktreeManager("/tmp")
    assert mgr.rollback(bad) is False


# --- remove -----------------------------------------------------------------


def test_remove_cleans_up_worktree(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("rm1")
    assert os.path.isdir(info.path)

    assert mgr.remove(info) is True
    assert not os.path.isdir(info.path)

    # The worktree is gone from git's bookkeeping too.
    listing = subprocess.run(
        ["git", "worktree", "list"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "run-rm1" not in listing


def test_remove_with_uncommitted_changes_force(repo):
    mgr = WorktreeManager(repo)
    info = mgr.create("rm2")
    f = os.path.join(info.path, "dirty.txt")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("dirty\n")

    # force=True (default) should remove even with a dirty worktree.
    assert mgr.remove(info, force=True) is True
    assert not os.path.isdir(info.path)
