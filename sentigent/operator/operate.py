"""operate() — the Operator control loop (design §4). Run a plan AS the user.

Ties the whole machine together: for each pending step it drives the worker
(claude -p), assesses risk (hard floor), judges with the profile gate, decides
whether to wake you, verifies the step actually got done, and checkpoints — all
persisted to the run/audit tables, all gated by the kill switch + budget.

Safety-first defaults:
  • execute=False (dry-run) — the worker is synthetic, nothing changes on disk.
    The full judgment/escalation/verify/persist loop still runs, so you can watch
    the machine end-to-end before trusting it to act.
  • On an escalation, the run PAUSES (status='waiting') and records the open
    escalation rather than blocking — you answer via operator_answer / the inbox /
    Telegram, then resume. No unattended blocking, no surprise actions.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.operator.escalation import EscalationDecider, ASSISTED
from sentigent.operator.gate import ProfileGate, CONTINUE, CORRECT
from sentigent.operator.plan import Plan, Step
from sentigent.operator.resolver import CloneResolver, APPROVE, SKIP
from sentigent.operator.risk import RiskAssessor
from sentigent.operator.runner import OperatorRunner
from sentigent.operator.safety import BudgetGovernor, KillSwitch
from sentigent.operator.verifier import Verifier


@dataclass
class StepOutcome:
    idx: int
    description: str
    status: str            # done | escalated | failed | killed | budget
    verdict: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    asked: bool = False
    headline: str = ""
    verified: bool = False
    checkpoint_sha: str = ""
    clone_resolved: bool = False     # the clone answered this blocker AS the user
    resolution: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "idx": self.idx, "description": self.description, "status": self.status,
            "verdict": self.verdict, "risk": self.risk, "asked": self.asked,
            "headline": self.headline, "verified": self.verified,
            "checkpoint_sha": self.checkpoint_sha,
            "clone_resolved": self.clone_resolved, "resolution": self.resolution,
        }


@dataclass
class RunResult:
    run_id: int
    goal: str
    autonomy: str
    status: str            # done | waiting | killed | budget_exhausted
    outcomes: list[StepOutcome] = field(default_factory=list)
    spent_usd: float = 0.0
    open_escalation_id: Optional[int] = None

    @property
    def steps_done(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "done")

    @property
    def asks(self) -> int:
        return sum(1 for o in self.outcomes if o.asked)

    @property
    def clone_resolves(self) -> int:
        return sum(1 for o in self.outcomes if o.clone_resolved)

    @property
    def autonomy_rate(self) -> float:
        """Of the blockers the clone faced (it resolved + it woke you), the fraction
        it resolved AS you without paging. The dark-factory metric. 1.0 if no blocker."""
        faced = self.clone_resolves + self.asks
        return (self.clone_resolves / faced) if faced else 1.0

    def digest(self) -> str:
        lines = [
            f"## Operator run #{self.run_id} — {self.status}",
            f"🎯 {self.goal}  ·  autonomy: {self.autonomy}  ·  spent ${self.spent_usd:.2f}",
            f"Σ {self.steps_done}/{len(self.outcomes)} steps done · {self.asks} asked you",
            "",
        ]
        for o in self.outcomes:
            icon = {"done": "✅", "escalated": "🔔", "failed": "⚠️",
                    "killed": "🛑", "budget": "💰"}.get(o.status, "•")
            lines.append(f"  {o.idx}. {icon} {o.status:<10} {o.description[:60]}")
            if o.asked and o.headline:
                lines.append(f"        🔔 {o.headline}")
        if self.status == "waiting" and self.open_escalation_id:
            lines.append("")
            lines.append(f"  ⏸ Waiting on you — escalation #{self.open_escalation_id}. "
                         f"Answer: operator_answer({self.open_escalation_id}, \"approve|skip|takeover\")")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "goal": self.goal, "autonomy": self.autonomy,
            "status": self.status, "spent_usd": round(self.spent_usd, 4),
            "steps_done": self.steps_done, "asks": self.asks,
            "clone_resolves": self.clone_resolves,
            "autonomy_rate": round(self.autonomy_rate, 3),
            "open_escalation_id": self.open_escalation_id,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


def _profile_system(profile: dict) -> str:
    """Compact 'act as me' system prompt injected into the worker (--append-system-prompt)."""
    p = profile or {}
    parts = [f"Act as this engineer. {p.get('summary','')}".strip()]
    for k, label in (("preferences", "Preferences"), ("coding_standards", "Standards"),
                     ("never_do", "Never")):
        vals = p.get(k) or []
        if vals:
            parts.append(f"{label}: " + "; ".join(str(v) for v in vals))
    return "\n".join(parts)


def _criteria_brief(crit: dict) -> str:
    """One-line human rendering of done-criteria for the worker prompt."""
    if not crit:
        return ""
    bits = []
    if crit.get("test_cmd"):
        bits.append(f"tests pass (`{crit['test_cmd']}`)")
    if crit.get("build_cmd"):
        bits.append(f"build passes (`{crit['build_cmd']}`)")
    if crit.get("files_exist"):
        bits.append("files exist: " + ", ".join(crit["files_exist"]))
    if isinstance(crit.get("grep"), dict):
        g = crit["grep"]
        bits.append(f"`{g.get('pattern','')}` present in {g.get('path','')}")
    if crit.get("diff_nonempty"):
        bits.append("a real code change is made")
    return "; ".join(bits)


def _step_prompt(plan: Plan, step: Step, prior: list[StepOutcome]) -> str:
    done = "; ".join(o.description for o in prior if o.status == "done") or "(none yet)"
    lines = [f"Goal: {plan.goal}"]
    phase = getattr(step, "phase", "")
    if phase:
        lines.append(f"Current phase: {phase}")
    lines.append(f"Already done: {done}")
    lines.append(f"Now do this step (and only this step): {step.description}")
    brief = _criteria_brief(getattr(step, "done_criteria", {}) or {})
    if brief:
        lines.append(f"This step is DONE only when: {brief}. Make sure it holds before finishing.")
    return "\n".join(lines) + "\n"


def operate(
    store: Any,
    plan: Plan,
    *,
    autonomy: str = ASSISTED,
    budget_usd: float = 2.0,
    execute: bool = False,
    runner: Optional[OperatorRunner] = None,
    repo_path: Optional[str] = None,
    worktree: Optional[Any] = None,        # a WorktreeManager (real execute only)
    killswitch: Optional[KillSwitch] = None,
    model: Optional[str] = None,
    max_attempts: int = 2,
    resume_run_id: Optional[int] = None,
    resolve: bool = True,
    resolver: Optional[CloneResolver] = None,
    resolver_thresholds: Optional[dict] = None,
) -> RunResult:
    """Drive a plan. Returns a persisted, inspectable RunResult. Never raises.

    When `resume_run_id` is set, the `plan` argument is IGNORED: the plan + step
    state are reconstructed from the persisted run, the newest answered escalation
    is applied to the step it paused on (approve → run it, skip → mark skipped,
    takeover → hand over the worktree), and the loop continues over only the still-
    pending steps under the SAME run id. Resuming never restarts from step 1.
    """
    # ── Resume: reconstruct the plan + run from persisted state ──────────────
    resume = resume_run_id is not None
    resume_decision = ""        # approve | skip | takeover  (for the paused step)
    resume_step_idx: Optional[int] = None
    run_row: dict = {}
    if resume:
        try:
            run_row = store.get_run(resume_run_id) or {}
        except Exception:
            run_row = {}
        plan_row = None
        steps_rows: list = []
        if run_row:
            try:
                plan_row = store.get_plan(run_row.get("plan_id"))
            except Exception:
                plan_row = None
            try:
                steps_rows = store.get_plan_steps(run_row.get("plan_id")) or []
            except Exception:
                steps_rows = []
        # Rebuild the Plan: a step is 'done' if its persisted status is done OR
        # skipped — either way it must NOT be re-run on resume.
        rebuilt = [
            Step(
                idx=int(r.get("idx", i + 1)),
                description=str(r.get("description", "")),
                done=str(r.get("status", "")) in ("done", "skipped"),
                done_criteria=_loads_criteria(r.get("done_criteria")),
            )
            for i, r in enumerate(steps_rows)
        ]
        plan = Plan(goal=(plan_row or {}).get("goal", "(resumed)"), steps=rebuilt)
        # Find the newest answered escalation → its decision + the paused step idx.
        try:
            answered = store.get_escalations(resume_run_id, status="answered") or []
        except Exception:
            answered = []
        if answered:
            esc = answered[0]   # newest first (ORDER BY id DESC)
            resume_decision = _normalize_decision(esc.get("user_decision", ""))
            try:
                ctx = esc.get("context")
                ctx = json.loads(ctx) if isinstance(ctx, str) else (ctx or {})
                resume_step_idx = ctx.get("step")
            except Exception:
                resume_step_idx = None

    # Load the model-of-you.
    profile: dict = {}
    try:
        latest = store.get_latest_operator_profile()
        if latest:
            profile = json.loads(latest.get("profile_json", "{}"))
    except Exception:
        pass
    try:
        practices = store.get_practices(active_only=True)
    except Exception:
        practices = []

    gate = ProfileGate(profile, practices, model=model)
    assessor = RiskAssessor()
    decider = EscalationDecider(autonomy)
    clone = resolver if resolver is not None else (
        CloneResolver(profile, store=store) if resolve else None
    )
    runner = runner or OperatorRunner(model=model, dry_run=not execute)
    ks = killswitch or KillSwitch()
    budget = BudgetGovernor(budget_usd)
    sysmsg = _profile_system(profile)

    # Map step idx → persisted plan_steps.id so we can update per-step status.
    step_id_by_idx: dict[int, int] = {}

    if resume:
        # Re-use the existing run + plan; don't start a second run.
        run_id = int(resume_run_id)
        plan_id = int(run_row.get("plan_id", 0) or 0)
        wt_path = str(run_row.get("worktree", "") or "")
        wt_info = None
        if execute and worktree is not None and wt_path:
            # Re-bind a WorktreeInfo to the already-created worktree dir so
            # checkpoints land in the same place across resume.
            wt_info = _existing_worktree_info(worktree, wt_path)
        try:
            for r in (store.get_plan_steps(plan_id) or []):
                step_id_by_idx[int(r.get("idx"))] = int(r.get("id"))
        except Exception:
            pass
    else:
        # Persist the plan + run.
        try:
            plan_id = store.save_plan(plan.goal, source=getattr(plan, "source", ""), status="running")
            for s in plan.steps:
                sid = store.save_plan_step(
                    plan_id, s.idx, s.description,
                    done_criteria=getattr(s, "done_criteria", {}) or {},
                )
                step_id_by_idx[s.idx] = sid
        except Exception:
            plan_id = 0
        wt_path = ""
        wt_info = None
        if execute and worktree is not None:
            try:
                wt_info = worktree.create(str(plan_id) or "run")
                wt_path = wt_info.path if (wt_info and wt_info.created) else ""
            except Exception:
                wt_info = None
        try:
            run_id = store.start_run(plan_id, autonomy_level=autonomy, budget_usd=budget_usd, worktree=wt_path)
        except Exception:
            run_id = 0

    result = RunResult(run_id=run_id, goal=plan.goal, autonomy=autonomy, status="done")

    def _event(etype: str, payload: dict, step_id: Optional[int] = None) -> None:
        try:
            store.add_run_event(run_id, etype, payload, step_id=step_id)
        except Exception:
            pass

    def _mark_step(idx: int, status: str, checkpoint_sha: str = "") -> None:
        sid = step_id_by_idx.get(idx)
        if not sid:
            return
        try:
            store.update_plan_step_status(sid, status, checkpoint_sha=checkpoint_sha)
        except Exception:
            pass

    # Execute=True but the worktree could not be created → NO isolation. Do not
    # pretend to execute. Escalate and stop rather than acting on the real tree.
    if execute and worktree is not None and not wt_path:
        try:
            eid = store.add_escalation(
                run_id, "Cannot execute: worktree creation failed (no isolation).",
                context={"trigger": "no_worktree"}, risk=1.0)
        except Exception:
            eid = None
        result.status = "waiting"
        result.open_escalation_id = eid
        _event("no_worktree", {"escalation_id": eid})
        try:
            store.update_run(run_id, status="waiting", spent_usd=0.0, ended_at_now=False)
        except Exception:
            pass
        return result

    _event("resumed" if resume else "run_started",
           {"autonomy": autonomy, "budget_usd": budget_usd,
            "execute": execute, "worktree": wt_path,
            **({"decision": resume_decision, "paused_step": resume_step_idx} if resume else {})})

    # ── Apply the human's decision to the paused step BEFORE continuing ──────
    if resume and resume_decision == "takeover":
        # The human takes the worktree; stop immediately.
        result.status = "handover"
        _event("handover", {"step": resume_step_idx, "worktree": wt_path})
        try:
            store.update_run(run_id, status="handover", spent_usd=result.spent_usd,
                             ended_at_now=True)
        except Exception:
            pass
        return result
    if resume and resume_decision == "skip" and resume_step_idx is not None:
        # Mark the paused step skipped and DON'T run it. The paused step is still
        # 'running' (not done) in the rebuilt plan, so flip it done in-memory too
        # to drop it from plan.pending below; persist 'skipped' + record the outcome.
        for s in plan.steps:
            if s.idx == resume_step_idx:
                s.done = True
        _mark_step(resume_step_idx, "skipped")
        result.outcomes.append(StepOutcome(resume_step_idx, _desc_for(plan, resume_step_idx),
                                           "skipped"))
        _event("step_skipped", {"step": resume_step_idx})
    # "approve" → the paused step is run normally below (it's still pending in the
    # rebuilt plan because we did NOT mark it done), proceeding past the gate the
    # human already cleared.

    seen_phase: Optional[str] = None
    for step in plan.pending:
        ph = getattr(step, "phase", "") or ""
        if ph and ph != seen_phase:
            seen_phase = ph
            _event("phase_started", {"phase": ph, "from_step": step.idx})
        # Kill switch — instant stop.
        if ks.is_tripped(str(run_id)) or ks.is_tripped(None):
            result.status = "killed"
            result.outcomes.append(StepOutcome(step.idx, step.description, "killed"))
            _event("killed", {"step": step.idx})
            break

        # ── Hard-floor PRE-FLIGHT: never drive the worker on a policy-wall step.
        # Risk is assessed on the step DESCRIPTION *before* any action, so a
        # force-push / prod-db / rm-rf / secret / external-send pauses the run
        # BEFORE the worker can act. A worktree contains file edits — it does NOT
        # contain a push to a shared remote, an rm outside the tree, or an
        # exfiltration. Resume-approve (the human already cleared this step)
        # bypasses the pre-flight so an approved hard-floor step can run.
        preflight = assessor.assess(step.description)
        cleared_by_human = (
            resume and resume_decision == "approve"
            and resume_step_idx is not None and step.idx == resume_step_idx
        )
        if preflight.policy_wall and not cleared_by_human:
            headline = f"Hard-floor step needs your OK before I run it: {step.description[:70]}"
            try:
                eid = store.add_escalation(
                    run_id, headline,
                    context={"step": step.idx, "trigger": "policy_wall_preflight",
                             "category": preflight.category},
                    risk=preflight.score, step_id=None,
                )
            except Exception:
                eid = None
            outcome = StepOutcome(
                step.idx, step.description, "escalated",
                risk={"score": round(preflight.score, 2), "category": preflight.category,
                      "level": preflight.level, "policy_wall": True},
                asked=True, headline=headline,
            )
            result.open_escalation_id = eid
            result.status = "waiting"
            _mark_step(step.idx, "running")  # paused before running; not done
            result.outcomes.append(outcome)
            _event("escalation", {"step": step.idx, "trigger": "policy_wall_preflight",
                                  "headline": headline, "escalation_id": eid})
            break

        # ── Drive + verify with self-repair retry (Task 10). Headless workers are
        # synthetic in dry-run. On a verify-fail we re-drive with the failure
        # context, up to max_attempts, before escalating.
        attempt = 0
        verified = False
        last_fail = ""
        turn = None
        b = None
        while attempt < max_attempts:
            attempt += 1
            prompt = _step_prompt(plan, step, result.outcomes)
            if last_fail:
                prompt += (f"\nThe previous attempt did NOT satisfy the done-criteria "
                           f"({last_fail}). Fix it now and make sure the criteria hold.\n")
            turn = runner.drive(prompt, system=sysmsg, workdir=wt_path or repo_path)
            b = budget.add(turn.input_tokens, turn.output_tokens)
            result.spent_usd = b.spent_usd
            if b.exceeded:
                break
            if not (execute and step.domain and wt_path):
                verified = not execute      # dry-run: nothing to verify
                break
            try:
                vres = Verifier(wt_path).verify(_coerce_criteria(step))
                verified = vres.done
                last_fail = "" if verified else vres.reason
            except Exception:
                verified = False
                last_fail = "verifier error"
            if verified:
                break

        # ── Diff-aware judge: the clone reviews the ACTUAL work (Task 9), not the plan.
        work_summary = (turn.actions_text if turn else "")
        if execute and wt_path:
            try:
                dp = subprocess.run(["git", "diff"], cwd=wt_path,
                                    capture_output=True, text=True, timeout=30)
                if dp.returncode == 0 and dp.stdout.strip():
                    work_summary += "\n--- diff ---\n" + dp.stdout[:4000]
            except Exception:
                pass
        risk = assessor.assess(step.description + "\n" + (turn.actions_text if turn else ""))
        verdict = gate.judge(step.description, risk_summary=f"{risk.level}/{risk.category}",
                            work=work_summary)
        esc = decider.decide(step.description, verdict, risk)
        # On resume-approve, the human already cleared the gate on the paused
        # step: run it through despite what the gate/decider says this time.
        if (resume and resume_decision == "approve"
                and resume_step_idx is not None and step.idx == resume_step_idx):
            esc = _no_ask(esc)
        outcome = StepOutcome(
            step.idx, step.description, "done",
            verdict=verdict.to_dict(),
            risk={"score": round(risk.score, 2), "category": risk.category,
                  "level": risk.level, "policy_wall": risk.policy_wall},
        )

        # Budget exhausted → stop and escalate.
        if b is not None and b.exceeded:
            outcome.status = "budget"
            result.status = "budget_exhausted"
            result.outcomes.append(outcome)
            _event("budget_exhausted", {"spent_usd": b.spent_usd, "limit": b.limit_usd})
            break

        # ── Clone Resolver: before waking the human, let the model-of-you answer
        # the blocker AS you. The whole point of the profile is to resolve this, not
        # just detect it. Hard rules (policy_wall) are never auto-cleared. If the
        # clone confidently approves → proceed; confidently skips → skip the step;
        # else fall through to paging the human (with the clone's attempt attached).
        cloned: Optional[Any] = None
        if esc.ask and clone is not None and not risk.policy_wall:
            blocker = {
                "step_text": step.description,
                "trigger": esc.trigger,
                "gate_reason": verdict.reason,
                "risk_level": risk.level,
                "category": esc.trigger,
            }
            try:
                cloned = clone.resolve(blocker)
            except Exception:
                cloned = None
            if cloned is not None and CloneResolver.should_apply(
                cloned, policy_wall=risk.policy_wall, category=esc.trigger,
                thresholds=resolver_thresholds,
            ):
                outcome.clone_resolved = True
                outcome.resolution = cloned.to_dict()
                if cloned.decision == SKIP:
                    outcome.status = "skipped"
                    _mark_step(step.idx, "skipped")
                    result.outcomes.append(outcome)
                    _event("clone_resolved", {"step": step.idx, "decision": SKIP,
                                              "confidence": cloned.confidence,
                                              "rationale": cloned.rationale,
                                              "trigger": esc.trigger})
                    continue
                # APPROVE → proceed exactly as a cleared step would.
                esc = _no_ask(esc)
                _event("clone_resolved", {"step": step.idx, "decision": APPROVE,
                                          "confidence": cloned.confidence,
                                          "rationale": cloned.rationale,
                                          "trigger": esc.trigger})

        # Wake the human? → record escalation, pause the run (no blocking).
        if esc.ask:
            outcome.status = "escalated"
            outcome.asked = True
            outcome.headline = esc.headline
            esc_ctx = {"step": step.idx, "trigger": esc.trigger, "verdict": verdict.to_dict()}
            if cloned is not None:
                # Show the human what the clone thought (and why it wasn't confident
                # enough to act) — and record the category so the answer can train it.
                esc_ctx["clone_attempt"] = cloned.to_dict()
                esc_ctx["category"] = esc.trigger
                outcome.resolution = cloned.to_dict()
            try:
                eid = store.add_escalation(
                    run_id, esc.headline, context=esc_ctx,
                    risk=risk.score, step_id=None,
                )
            except Exception:
                eid = None
            result.open_escalation_id = eid
            result.status = "waiting"
            _mark_step(step.idx, "running")  # paused mid-step; not done
            result.outcomes.append(outcome)
            _event("escalation", {"step": step.idx, "trigger": esc.trigger,
                                  "headline": esc.headline, "escalation_id": eid})
            break

        # Verify result (real execute only). After max_attempts, an unverified
        # step is surfaced rather than trusted.
        if execute and step.domain and wt_path:
            outcome.verified = verified
            if not outcome.verified:
                outcome.status = "failed"
                result.status = "waiting"
                try:
                    eid = store.add_escalation(
                        run_id,
                        f"Step {step.idx} not verified done after {attempt} attempt(s): {step.description[:60]}",
                        context={"step": step.idx, "trigger": "verify_failed", "reason": last_fail},
                        risk=risk.score)
                except Exception:
                    eid = None
                result.open_escalation_id = eid
                _mark_step(step.idx, "failed")
                result.outcomes.append(outcome)
                _event("verify_failed", {"step": step.idx, "escalation_id": eid, "reason": last_fail})
                break
        else:
            outcome.verified = not execute  # dry-run: nothing to verify

        # Checkpoint (real execute only).
        if execute and worktree is not None and wt_info is not None:
            try:
                sha = worktree.checkpoint(wt_info, f"sentigent: step {step.idx} — {step.description[:50]}")
                outcome.checkpoint_sha = sha or ""
            except Exception:
                pass

        _mark_step(step.idx, "done", checkpoint_sha=outcome.checkpoint_sha)
        result.outcomes.append(outcome)
        corr = "" if verdict.decision == CONTINUE else f" (auto-corrected: {verdict.correction})"
        _event("step_done", {"step": step.idx, "step_text": step.description,
                             "verdict": verdict.to_dict(),
                             "checkpoint": outcome.checkpoint_sha, "note": corr})

    # Close the run.
    final = "completed" if result.status == "done" else result.status
    try:
        store.update_run(run_id, status=final, spent_usd=result.spent_usd, ended_at_now=(result.status != "waiting"))
    except Exception:
        pass
    _event("run_ended", {"status": final, "spent_usd": result.spent_usd,
                         "steps_done": result.steps_done})
    return result


def _normalize_decision(raw: str) -> str:
    """Map a human's free-text escalation answer to one of approve|skip|takeover."""
    d = (raw or "").strip().lower()
    if d in ("approve", "yes", "continue", "ok", "go", "proceed", "y"):
        return "approve"
    if d in ("skip", "next", "ignore", "drop"):
        return "skip"
    if d in ("takeover", "take over", "take-over", "handover", "hand over", "stop"):
        return "takeover"
    return d  # unrecognized → leave as-is (treated as no special action)


def _no_ask(esc: Any) -> Any:
    """Return an escalation-decision clone that won't ask (resume-approve override)."""
    try:
        esc.ask = False
    except Exception:
        pass
    return esc


def _desc_for(plan: Plan, idx: int) -> str:
    for s in plan.steps:
        if s.idx == idx:
            return s.description
    return ""


def _existing_worktree_info(worktree: Any, wt_path: str) -> Optional[Any]:
    """Rebind a WorktreeInfo to an already-created worktree dir (resume). The base
    sha is read back from the worktree so checkpoint diffs still work; fail-soft."""
    try:
        from sentigent.operator.worktree import WorktreeInfo
        import os as _os
        if not wt_path or not _os.path.isdir(wt_path):
            return None
        head = worktree._head_sha(wt_path) if hasattr(worktree, "_head_sha") else None
        return WorktreeInfo(path=wt_path, branch="", base_sha=head or "", created=True)
    except Exception:
        return None


def _coerce_criteria(step: Step) -> dict:
    """Best-effort done-criteria for a step. If none were authored, fall back to
    'something changed' (diff_nonempty) so the verifier isn't a no-op."""
    raw = getattr(step, "done_criteria", None)
    if isinstance(raw, dict) and raw:
        return raw
    if isinstance(raw, str) and raw.strip() and raw.strip() not in ("{}", ""):
        try:
            d = json.loads(raw)
            if isinstance(d, dict) and d:
                return d
        except Exception:
            pass
    return {"diff_nonempty": True}


def _loads_criteria(raw) -> dict:
    """Parse a persisted done_criteria cell (JSON string or dict) -> dict; {} on failure."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}
