"""Operator Verifier — the anti-hallucination gate (B4).

"Don't trust 'Claude said done'." A plan step claims completion; this module
checks whether it is ACTUALLY done by running concrete done-criteria in a
workdir: tests, a build, file existence, a non-empty diff, a grep.

Conservative by design: if a check cannot be run (timeout, crash, missing tool,
empty criteria), it FAILS rather than passing. A false "done" is worse than an
extra ask. Nothing destructive ever runs here — only read/inspect/run-as-told.

`done` is True only if EVERY requested check passed AND at least one real check
actually ran. Empty criteria → done=False with a single `no_criteria` check.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    kind: str        # test | files_exist | diff_nonempty | build | grep | no_criteria
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "passed": self.passed, "detail": self.detail}


@dataclass
class VerifyResult:
    done: bool                              # True iff EVERY requested check passed (AND)
    reason: str
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "done": self.done,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
        }


class Verifier:
    """Runs done-criteria in a workdir. Conservative: if a check can't be run, it
    FAILS (better to ask than to falsely claim done). Nothing destructive."""

    def __init__(self, workdir: str, timeout: float = 300.0) -> None:
        self.workdir = workdir
        self.timeout = timeout

    # -- individual checks -------------------------------------------------

    def _run_cmd(self, kind: str, cmd: str) -> CheckResult:
        """Run a shell command in the workdir; passed iff exit code 0.
        Any timeout/exception fails the check with the error in detail."""
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(kind, False, f"timed out after {self.timeout}s: {cmd!r}")
        except Exception as e:  # noqa: BLE001 — fail-soft on any spawn error
            return CheckResult(kind, False, f"error running {cmd!r}: {e}")
        passed = proc.returncode == 0
        tail = (proc.stderr or proc.stdout or "").strip()
        if len(tail) > 500:
            tail = tail[-500:]
        detail = f"exit={proc.returncode} cmd={cmd!r}"
        if tail:
            detail += f" :: {tail}"
        return CheckResult(kind, passed, detail)

    def _check_files_exist(self, paths: list[str]) -> CheckResult:
        missing = []
        for p in paths:
            full = p if os.path.isabs(p) else os.path.join(self.workdir, p)
            if not os.path.exists(full):
                missing.append(p)
        if missing:
            return CheckResult("files_exist", False, f"missing: {missing}")
        return CheckResult("files_exist", True, f"all {len(paths)} path(s) exist")

    def _check_diff_nonempty(self) -> CheckResult:
        # Decide PASS/FAIL on `git status --porcelain`: it reports staged,
        # unstaged AND untracked changes. `git diff --stat` alone is blind to
        # brand-new untracked files, which is exactly what a fresh worker step
        # (e.g. `claude -p` creating a new file) produces — so a real change
        # would look like "nothing happened" and the step would wrongly fail.
        try:
            status = subprocess.run(
                "git status --porcelain",
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return CheckResult("diff_nonempty", False, f"git status timed out after {self.timeout}s")
        except Exception as e:  # noqa: BLE001
            return CheckResult("diff_nonempty", False, f"error running git status: {e}")
        if status.returncode != 0:
            err = (status.stderr or status.stdout or "").strip()
            return CheckResult("diff_nonempty", False, f"git status failed (exit={status.returncode}): {err}")
        porcelain = (status.stdout or "").strip()
        if not porcelain:
            return CheckResult("diff_nonempty", False, "git status shows no staged, unstaged, or untracked changes")

        # There ARE changes. Prefer a readable --stat headline for tracked edits;
        # fall back to a count of porcelain entries (covers untracked-only steps).
        for args in ("git diff --stat", "git diff --cached --stat"):
            try:
                proc = subprocess.run(
                    args, shell=True, cwd=self.workdir,
                    capture_output=True, text=True, timeout=self.timeout,
                )
            except Exception:  # noqa: BLE001
                continue
            if proc.returncode == 0:
                out = (proc.stdout or "").strip()
                if out:
                    return CheckResult("diff_nonempty", True, out.splitlines()[-1].strip())
        n = len(porcelain.splitlines())
        return CheckResult("diff_nonempty", True, f"{n} new/changed file(s) (incl. untracked)")

    def _check_grep(self, spec: dict) -> CheckResult:
        pattern = (spec or {}).get("pattern")
        path = (spec or {}).get("path")
        if not pattern or not path:
            return CheckResult("grep", False, "grep needs both 'pattern' and 'path'")
        full = path if os.path.isabs(path) else os.path.join(self.workdir, path)
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return CheckResult("grep", False, f"bad regex {pattern!r}: {e}")
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except FileNotFoundError:
            return CheckResult("grep", False, f"file not found: {path}")
        except Exception as e:  # noqa: BLE001
            return CheckResult("grep", False, f"error reading {path}: {e}")
        if rx.search(text):
            return CheckResult("grep", True, f"pattern {pattern!r} found in {path}")
        return CheckResult("grep", False, f"pattern {pattern!r} NOT found in {path}")

    # -- orchestration -----------------------------------------------------

    def verify(self, criteria: dict) -> VerifyResult:
        criteria = criteria or {}
        checks: list[CheckResult] = []

        if "test_cmd" in criteria:
            checks.append(self._run_cmd("test", str(criteria["test_cmd"])))
        if "build_cmd" in criteria:
            checks.append(self._run_cmd("build", str(criteria["build_cmd"])))
        if "files_exist" in criteria:
            paths = criteria["files_exist"] or []
            if isinstance(paths, str):
                paths = [paths]
            checks.append(self._check_files_exist(list(paths)))
        if criteria.get("diff_nonempty"):
            checks.append(self._check_diff_nonempty())
        if "grep" in criteria:
            checks.append(self._check_grep(criteria["grep"]))

        if not checks:
            return VerifyResult(
                done=False,
                reason="no done-criteria",
                checks=[CheckResult("no_criteria", False, "no verifiable done-criteria supplied")],
            )

        all_passed = all(c.passed for c in checks)
        if all_passed:
            reason = f"all {len(checks)} check(s) passed"
        else:
            failed = [c.kind for c in checks if not c.passed]
            reason = f"failed check(s): {failed}"
        return VerifyResult(done=all_passed, reason=reason, checks=checks)
