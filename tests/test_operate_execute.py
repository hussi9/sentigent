"""End-to-end EXECUTE-MODE proof: the Verifier actually fires inside operate() and gates the
step (D-019 — closes the long-standing gap-3 "execute-mode verify is unproven").

This drives the real operate() loop with execute=True against:
  • a real MemoryStore (temp sqlite) — real persistence,
  • a real temp git worktree — real isolation + real `git status`/checkpoint,
  • real subprocess `test_cmd` done-criteria run by the real Verifier,
only INJECTING the LLM worker (OperatorRunner) and the CloneResolver. The worker is injected on
purpose: gap-3 is about the verifier firing in execute mode, not about an LLM writing code — and a
test must never burn real Anthropic quota. Everything that makes the gate real (subprocess test
execution, git diff, checkpoint commit, self-repair retry) runs for real here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator.operate import operate
from sentigent.operator.plan import Plan, Step
from sentigent.operator.escalation import ASSISTED
from sentigent.operator.runner import OperatorRunner, TurnResult
from sentigent.operator.resolver import Resolution, APPROVE

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _WTInfo:
    def __init__(self, path: str):
        self.path = path
        self.created = True


class _FakeWorktree:
    """Hands operate() a real, already-initialized git repo as the 'worktree'."""
    def __init__(self, path: str):
        self._path = path

    def create(self, _name: str) -> _WTInfo:
        return _WTInfo(self._path)

    def checkpoint(self, info: _WTInfo, msg: str) -> str:
        _git(["add", "-A"], info.path)
        subprocess.run(["git", "commit", "-qm", msg], cwd=info.path,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=info.path,
                           capture_output=True, text=True)
        return r.stdout.strip()


class _FileWritingRunner(OperatorRunner):
    """A real (non-dry-run) worker stand-in: actually writes a file into the worktree, like a
    real `claude -p` step would, and counts how many times it was driven (to prove self-repair)."""
    def __init__(self, filename: str):
        super().__init__(dry_run=False)
        self.filename = filename
        self.calls = 0

    def drive(self, prompt: str, *, system: str = "", workdir=None) -> TurnResult:
        self.calls += 1
        with open(os.path.join(workdir, self.filename), "w", encoding="utf-8") as fh:
            fh.write("work output\n")
        return TurnResult(ok=True, text="wrote the file", input_tokens=10, output_tokens=5)


class _ApprovingResolver:
    """Stands in for the clone so the offline-LLM gate's low-confidence ask is auto-cleared —
    keeps the test focused on the VERIFIER, not the gate. (policy_wall is still honored upstream.)"""
    def resolve(self, _blocker) -> Resolution:
        return Resolution(APPROVE, 0.99, "test: clone approves", source="llm")


@pytest.fixture
def repo():
    d = tempfile.mkdtemp(prefix="op_exec_")
    _git(["init"], d)
    _git(["config", "user.email", "t@t.test"], d)
    _git(["config", "user.name", "t"], d)
    with open(os.path.join(d, "seed.txt"), "w") as fh:
        fh.write("seed\n")
    _git(["add", "-A"], d)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-exec", org_id="t", db_path=os.path.join(d, "m.db"))


def test_execute_passing_test_cmd_verifies_and_checkpoints(store, repo):
    # The worker writes made.txt; the done-criteria test_cmd checks made.txt exists → PASS.
    runner = _FileWritingRunner("made.txt")
    plan = Plan(goal="prove verify passes", steps=[
        Step(idx=1, description="create made.txt", domain="test",
             done_criteria={"test_cmd": "test -f made.txt"}),
    ])
    res = operate(store, plan, autonomy=ASSISTED, execute=True,
                  runner=runner, worktree=_FakeWorktree(repo),
                  resolver=_ApprovingResolver(), max_attempts=2)

    assert runner.calls >= 1                         # the worker really ran
    assert res.outcomes, "expected a step outcome"
    oc = res.outcomes[-1]
    assert oc.verified is True                        # the REAL verifier ran the REAL test_cmd
    assert oc.status == "done"
    assert oc.checkpoint_sha                          # a real git checkpoint commit was made
    assert os.path.isfile(os.path.join(repo, "made.txt"))


def test_execute_failing_test_cmd_blocks_and_self_repairs(store, repo):
    # test_cmd checks for a file the worker never creates → the verifier FAILS every attempt,
    # so the loop must self-repair up to max_attempts, then refuse to mark the step done.
    runner = _FileWritingRunner("made.txt")           # writes made.txt...
    plan = Plan(goal="prove verify blocks", steps=[
        Step(idx=1, description="create the artifact", domain="test",
             done_criteria={"test_cmd": "test -f never_created.txt"}),  # ...but checks a diff file
    ])
    res = operate(store, plan, autonomy=ASSISTED, execute=True,
                  runner=runner, worktree=_FakeWorktree(repo),
                  resolver=_ApprovingResolver(), max_attempts=2)

    assert runner.calls == 2                          # self-repair retried up to max_attempts
    oc = res.outcomes[-1]
    assert oc.verified is False                       # the gate refused to falsely pass
    assert oc.status == "failed"
    assert res.status == "waiting"                    # run paused for the human
    escs = store.get_escalations(res.run_id) or []
    assert any("not verified" in str(e.get("question", "")).lower() for e in escs)
