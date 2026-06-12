"""Tests for Fly-mode real-execute + resume-from-escalation (design §4).

Three behaviors:
  1. execute=True against a real temp git repo + WorktreeManager — a benign plan
     runs, the worktree gets a checkpoint sha, and plan_steps are marked 'done'.
  2. A policy-wall step pauses (waiting + open escalation). After the user answers
     'skip', operator resume continues: the skipped step is NOT run, later steps
     proceed, and already-done earlier steps are NOT redone.
  3. A 'takeover' answer → resume returns status 'handover'.

The gate is forced offline (heuristic) so it never reaches Ollama; autonomy is
'trusted' so the offline-heuristic's low confidence won't trigger an ask on benign
steps — only the inviolable policy wall does.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.operator import gate as gate_mod
from sentigent.operator.operate import operate
from sentigent.operator.plan import parse_plan
from sentigent.operator.runner import TurnResult
from sentigent.operator.worktree import WorktreeManager


# ---- fixtures -----------------------------------------------------------------

@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(agent_id="t-op-resume", org_id="t", db_path=Path(d) / "m.db")
        s.save_operator_profile('{"summary":"ships fast","source":"llm"}', source="llm")
        yield s


@pytest.fixture(autouse=True)
def _offline_gate(monkeypatch):
    # Force the ProfileGate onto its deterministic heuristic (no Ollama in tests).
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: False)


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def git_repo():
    """A real, committed temp git repo so the worktree + Verifier can operate."""
    with tempfile.TemporaryDirectory() as d:
        _git(["init", "-q"], d)
        _git(["config", "user.email", "t@t.t"], d)
        _git(["config", "user.name", "t"], d)
        _git(["config", "commit.gpgsign", "false"], d)
        (Path(d) / "README.md").write_text("seed\n")
        _git(["add", "-A"], d)
        _git(["commit", "-q", "-m", "seed"], d)
        yield d


class FileWritingRunner:
    """Like the dry-run FakeRunner, but writes a real file into `workdir` on each
    drive — so the Verifier's diff_nonempty check sees real changes in execute mode."""

    def __init__(self, in_tok=10, out_tok=5):
        self.in_tok, self.out_tok = in_tok, out_tok
        self.calls = 0
        self.workdirs: list = []

    def drive(self, prompt, *, system="", workdir=None):
        self.calls += 1
        self.workdirs.append(workdir)
        if workdir:
            try:
                # Unique file + content per drive (uuid) so each drive is a genuine
                # change in the worktree — never colliding with a previously
                # committed file across runs (resume reuses the same worktree).
                import uuid as _uuid
                token = _uuid.uuid4().hex[:8]
                p = Path(workdir) / f"work_{token}.txt"
                p.write_text(f"work from drive #{self.calls} [{token}]\n{prompt[:80]}\n")
                # Stage it so the Verifier's git-diff-based diff_nonempty check sees
                # the change (untracked files don't show in `git diff`). A real
                # claude worker's edits get checkpointed via `git add -A` anyway.
                subprocess.run(["git", "add", "-A"], cwd=workdir,
                               capture_output=True, text=True)
            except Exception:
                pass
        return TurnResult(ok=True, text="did it", input_tokens=self.in_tok,
                          output_tokens=self.out_tok, dry_run=False)


# ---- 1. real execute with worktree + checkpoint -------------------------------

@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_execute_real_worktree_checkpoints_and_marks_done(store, git_repo):
    plan = parse_plan("# demo\n- [ ] write the first note file\n- [ ] write the second note file\n")
    runner = FileWritingRunner()
    wt = WorktreeManager(git_repo)

    res = operate(store, plan, autonomy="trusted", runner=runner,
                  execute=True, worktree=wt, repo_path=git_repo)

    assert res.status == "done", res.digest()
    assert res.steps_done == 2
    assert runner.calls == 2
    # every drive ran inside the worktree, not the source repo
    assert all(w and w != git_repo and ".sentigent-worktrees" in w for w in runner.workdirs)
    # each step got a real checkpoint sha
    shas = [o.checkpoint_sha for o in res.outcomes]
    assert all(shas), shas
    assert len(set(shas)) == 2  # two distinct commits

    # plan_steps persisted as 'done'
    plan_id = store.get_run(res.run_id)["plan_id"]
    steps = store.get_plan_steps(plan_id)
    assert {s["status"] for s in steps} == {"done"}
    assert all(s["checkpoint_sha"] for s in steps)


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_execute_without_isolation_escalates(store, git_repo):
    """execute=True but the WorktreeManager points at a NON-git dir → creation fails
    → must NOT pretend to execute; escalate + stop instead."""
    with tempfile.TemporaryDirectory() as nongit:
        plan = parse_plan("# demo\n- [ ] write a note\n")
        res = operate(store, plan, autonomy="trusted", runner=FileWritingRunner(),
                      execute=True, worktree=WorktreeManager(nongit), repo_path=nongit)
    assert res.status == "waiting"
    assert res.open_escalation_id is not None
    assert res.steps_done == 0


# ---- 2. pause on policy wall, then resume with 'skip' -------------------------

@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_resume_skip_does_not_rerun_done_steps(store, git_repo):
    plan = parse_plan(
        "# demo\n"
        "- [ ] write the first note\n"
        "- [ ] git push --force origin main\n"
        "- [ ] write the third note\n"
    )
    runner1 = FileWritingRunner()
    wt = WorktreeManager(git_repo)
    res1 = operate(store, plan, autonomy="trusted", runner=runner1,
                   execute=True, worktree=wt, repo_path=git_repo)

    # paused on the force-push (policy wall), step 1 already done
    assert res1.status == "waiting"
    assert res1.open_escalation_id is not None
    assert res1.steps_done == 1
    # Only step 1 was driven. The force-push (step 2) is a hard-floor policy-wall
    # step, so the pre-flight gate pauses the run BEFORE the worker is ever driven
    # — the dangerous command must not run unattended.
    assert runner1.calls == 1

    plan_id = store.get_run(res1.run_id)["plan_id"]
    by_idx = {s["idx"]: s for s in store.get_plan_steps(plan_id)}
    assert by_idx[1]["status"] == "done"
    assert by_idx[2]["status"] == "running"   # paused mid-step
    assert by_idx[3]["status"] == "pending"

    # user answers 'skip' on the open escalation, then resumes
    eid = res1.open_escalation_id
    store.answer_escalation(eid, "skip")

    runner2 = FileWritingRunner()
    res2 = operate(store, parse_plan("# ignored\n- [ ] ignored\n"),
                   autonomy="trusted", runner=runner2,
                   execute=True, worktree=wt, repo_path=git_repo,
                   resume_run_id=res1.run_id)

    assert res2.status == "done", res2.digest()
    # only step 3 was actually driven on resume — NOT step 1 (done) or step 2 (skipped)
    assert runner2.calls == 1

    by_idx2 = {s["idx"]: s for s in store.get_plan_steps(plan_id)}
    assert by_idx2[1]["status"] == "done"
    assert by_idx2[2]["status"] == "skipped"
    assert by_idx2[3]["status"] == "done"

    # a 'resumed' event was logged on the same run id (not a new run)
    types = {e["type"] for e in store.get_run_events(res1.run_id)}
    assert "resumed" in types
    assert "step_skipped" in types


# ---- 2a-pre. hard-floor pre-flight: never drive the worker on a policy wall ---

@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_policy_wall_step_is_not_driven(store, git_repo):
    """The load-bearing safety guarantee: a hard-floor step (force-push) must
    pause BEFORE the worker runs — the worker is never driven on it."""
    plan = parse_plan("# demo\n- [ ] git push --force origin main\n")
    runner = FileWritingRunner()
    res = operate(store, plan, autonomy="trusted", runner=runner,
                  execute=True, worktree=WorktreeManager(git_repo), repo_path=git_repo)
    assert res.status == "waiting"
    assert res.open_escalation_id is not None
    assert runner.calls == 0          # worker NEVER ran the dangerous step
    assert res.steps_done == 0
    # the escalation records the pre-flight trigger
    escs = store.get_open_escalations(res.run_id)
    assert escs and escs[0].get("context")
    import json as _json
    raw = escs[0]["context"]
    ctx = _json.loads(raw) if isinstance(raw, str) else raw
    assert ctx.get("trigger") == "policy_wall_preflight"


# ---- 2b. resume with 'approve' → runs the paused step ------------------------

@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_resume_approve_runs_paused_step(store, git_repo):
    plan = parse_plan(
        "# demo\n"
        "- [ ] write the first note\n"
        "- [ ] git push --force origin main\n"
    )
    wt = WorktreeManager(git_repo)
    res1 = operate(store, plan, autonomy="trusted", runner=FileWritingRunner(),
                   execute=True, worktree=wt, repo_path=git_repo)
    assert res1.status == "waiting" and res1.steps_done == 1
    plan_id = store.get_run(res1.run_id)["plan_id"]

    # approve the paused force-push: on resume it runs despite the earlier gate ask
    store.answer_escalation(res1.open_escalation_id, "approve")
    runner2 = FileWritingRunner()
    res2 = operate(store, parse_plan("# ignored\n- [ ] ignored\n"),
                   autonomy="trusted", runner=runner2,
                   execute=True, worktree=wt, repo_path=git_repo,
                   resume_run_id=res1.run_id)

    assert res2.status == "done", res2.digest()
    assert runner2.calls == 1  # only the approved (paused) step 2 re-ran, step 1 not redone
    by_idx = {s["idx"]: s for s in store.get_plan_steps(plan_id)}
    assert by_idx[1]["status"] == "done"
    assert by_idx[2]["status"] == "done"


# ---- 3. resume with 'takeover' → handover ------------------------------------

@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_resume_takeover_returns_handover(store, git_repo):
    plan = parse_plan(
        "# demo\n- [ ] write a note\n- [ ] git push --force origin main\n"
    )
    wt = WorktreeManager(git_repo)
    res1 = operate(store, plan, autonomy="trusted", runner=FileWritingRunner(),
                   execute=True, worktree=wt, repo_path=git_repo)
    assert res1.status == "waiting"

    store.answer_escalation(res1.open_escalation_id, "takeover")
    res2 = operate(store, parse_plan("# ignored\n- [ ] ignored\n"),
                   autonomy="trusted", runner=FileWritingRunner(),
                   execute=True, worktree=wt, repo_path=git_repo,
                   resume_run_id=res1.run_id)

    assert res2.status == "handover"
    types = {e["type"] for e in store.get_run_events(res1.run_id)}
    assert "handover" in types
    # run row recorded the handover status
    assert store.get_run(res1.run_id)["status"] == "handover"
