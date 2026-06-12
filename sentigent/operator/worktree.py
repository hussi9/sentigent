"""WorktreeManager (C4) — git-worktree blast-radius isolation for an unattended run.

When the operator runs in Fly mode it must not touch the user's working tree. This
module carves out a disposable git worktree on a fresh branch ('sentigent/run-<id>'),
lets the operator commit checkpoints inside it, exposes a diff of everything it did,
and can roll the worktree back to its creation point or remove it entirely.

Every git call is fail-soft: it goes through subprocess.run with a timeout and is
wrapped so a failure (or a missing/non-git repo) degrades gracefully — created=False,
diff=='', checkpoint==None, rollback/remove==False — instead of raising. The orchestrator
composes this; nothing here decides policy.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

_TIMEOUT = 60  # seconds — git ops on a local repo are fast; this is a safety net


@dataclass
class WorktreeInfo:
    path: str          # absolute path of the worktree dir
    branch: str        # the operator branch name
    base_sha: str      # HEAD sha of the source repo at creation
    created: bool      # False if creation failed


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess | None:
    """Run a git command fail-soft. Returns the CompletedProcess, or None on any error."""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except Exception:
        return None


def _ok(proc: subprocess.CompletedProcess | None) -> bool:
    return proc is not None and proc.returncode == 0


class WorktreeManager:
    """Manages a single source repo's disposable operator worktrees."""

    WORKTREE_DIRNAME = ".sentigent-worktrees"

    def __init__(self, repo_path: str) -> None:
        self.repo_path = os.path.abspath(repo_path)

    # --- internal helpers -------------------------------------------------

    def _is_git_repo(self, path: str) -> bool:
        proc = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
        return _ok(proc) and (proc.stdout or "").strip() == "true"

    def _head_sha(self, path: str) -> str | None:
        proc = _run(["git", "rev-parse", "HEAD"], cwd=path)
        if not _ok(proc):
            return None
        sha = (proc.stdout or "").strip()
        return sha or None

    # --- public API -------------------------------------------------------

    def create(self, run_id: str) -> WorktreeInfo:
        """`git worktree add` a fresh branch for the run.

        Worktree dir: <repo>/.sentigent-worktrees/run-<run_id>
        Branch:       sentigent/run-<run_id>
        created=False on any failure or if repo_path isn't a git repo.
        """
        branch = f"sentigent/run-{run_id}"
        wt_dir = os.path.join(self.repo_path, self.WORKTREE_DIRNAME, f"run-{run_id}")

        failed = WorktreeInfo(path=wt_dir, branch=branch, base_sha="", created=False)

        if not self._is_git_repo(self.repo_path):
            return failed

        base_sha = self._head_sha(self.repo_path)
        if not base_sha:
            return failed

        # `git worktree add -b <branch> <dir> <base_sha>` creates the branch at base
        # and checks it out in the new worktree dir in one shot.
        proc = _run(
            ["git", "worktree", "add", "-b", branch, wt_dir, base_sha],
            cwd=self.repo_path,
        )
        if not _ok(proc) or not os.path.isdir(wt_dir):
            return failed

        return WorktreeInfo(
            path=os.path.abspath(wt_dir),
            branch=branch,
            base_sha=base_sha,
            created=True,
        )

    def checkpoint(self, info: WorktreeInfo, message: str) -> str | None:
        """`git add -A` + commit IN the worktree.

        Returns the new commit sha, or None if there's nothing to commit / failure.
        """
        if not info.created or not os.path.isdir(info.path):
            return None

        if not _ok(_run(["git", "add", "-A"], cwd=info.path)):
            return None

        # Nothing staged? `git diff --cached --quiet` exits 0 when there are no
        # staged changes — in that case there's nothing to commit.
        staged = _run(["git", "diff", "--cached", "--quiet"], cwd=info.path)
        if staged is None:
            return None
        if staged.returncode == 0:
            return None  # clean — nothing to checkpoint

        commit = _run(["git", "commit", "-m", message], cwd=info.path)
        if not _ok(commit):
            return None

        return self._head_sha(info.path)

    def diff(self, info: WorktreeInfo) -> str:
        """Combined diff: committed-since-base + current working-tree changes.

        Returns '' on failure.
        """
        if not info.created or not os.path.isdir(info.path):
            return ""

        parts: list[str] = []

        # Committed work since the base sha (checkpoints).
        if info.base_sha:
            committed = _run(["git", "diff", info.base_sha, "HEAD"], cwd=info.path)
            if committed is None:
                return ""
            if committed.returncode == 0 and committed.stdout:
                parts.append(committed.stdout)

        # Uncommitted working-tree changes (includes untracked via add -N).
        # Stage intents for untracked files so they appear in `git diff`.
        _run(["git", "add", "-N", "."], cwd=info.path)
        working = _run(["git", "diff"], cwd=info.path)
        if working is None:
            return ""
        if working.returncode == 0 and working.stdout:
            parts.append(working.stdout)

        return "".join(parts)

    def rollback(self, info: WorktreeInfo) -> bool:
        """`git reset --hard <base_sha>` in the worktree."""
        if not info.created or not info.base_sha or not os.path.isdir(info.path):
            return False
        return _ok(_run(["git", "reset", "--hard", info.base_sha], cwd=info.path))

    def remove(self, info: WorktreeInfo, force: bool = True) -> bool:
        """`git worktree remove` the dir, then prune. Returns True on success."""
        if not info.path:
            return False

        args = ["git", "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(info.path)

        removed = _run(args, cwd=self.repo_path)
        # Prune dangling worktree metadata regardless (best-effort).
        _run(["git", "worktree", "prune"], cwd=self.repo_path)

        return _ok(removed)
