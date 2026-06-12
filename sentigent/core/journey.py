"""Journey — the capstone "where am I in the 5-step clone lifecycle + next move".

The product's spine, made legible at a glance. Five steps:

  1. Create clone   — Sentigent shadows your vibe-coding (signal = decision events)
  2. Review         — good / bad / gaps via profile_review
  3. Improve        — adopt best practices into the playbook
  4. Reverse shadow — watch the clone judge/operate in dry-run
  5. Fly mode       — the clone executes a real plan via `claude -p`, escalating

This surface answers two questions deterministically and fast (SessionStart-grade,
no LLM, never raises): *which rung am I on?* and *what's the single most valuable
next move?* It reads only real signal from the live store — the same honest-by-
construction principle as CloneReadiness, which it reuses for the % and the early-
stage next-action fallback.

Run-history detection (steps 4 & 5) reads the operator_runs table directly,
read-only and fail-soft, rather than adding a store method: a dry-run leaves an
empty `worktree`; a real execute run records a worktree path. If the table can't
be read at all, those stages stay honestly 'active' once unlocked and say so.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from sentigent.core import clone_readiness, profile_review

# A real shadowing signal: enough captured decisions that step 1 is genuinely "on".
_CREATE_DONE_EVENTS = 10
_CREATE_DONE_EPISODES = 200   # a real shadow corpus locks step 1 on its own

_STAGE_NAMES = {
    1: "Create clone",
    2: "Review",
    3: "Improve",
    4: "Reverse shadow",
    5: "Fly mode",
}

_ICON = {"done": "✅", "active": "▶️", "locked": "🔒"}


@dataclass
class Stage:
    num: int            # 1..5
    name: str           # "Create clone" ...
    status: str         # done | active | locked
    detail: str         # one plain-language line of evidence ("47 decisions captured")

    def to_dict(self) -> dict:
        return {"num": self.num, "name": self.name, "status": self.status,
                "detail": self.detail}


@dataclass
class Journey:
    readiness_pct: int
    current_stage: int          # the lowest not-yet-"done" stage = where the user is
    stages: list[Stage] = field(default_factory=list)
    next_action: str = ""       # the single most valuable next move
    waiting_escalations: int = 0  # open operator escalations

    def to_dict(self) -> dict:
        return {
            "readiness_pct": self.readiness_pct,
            "current_stage": self.current_stage,
            "next_action": self.next_action,
            "waiting_escalations": self.waiting_escalations,
            "stages": [s.to_dict() for s in self.stages],
        }

    def render(self) -> str:
        """A 5-row ladder with ✅/▶️/🔒 + the next move. Markdown."""
        lines = [
            f"# Your clone — the 5-step journey",
            "",
            f"**Readiness {self.readiness_pct}%** · "
            f"{clone_readiness.render_bar(self.readiness_pct)}",
            "",
        ]
        for s in self.stages:
            icon = _ICON.get(s.status, "·")
            here = "  ← you are here" if s.num == self.current_stage else ""
            lines.append(f"{icon} **{s.num}. {s.name}** — {s.detail}{here}")
        lines.append("")
        if self.waiting_escalations:
            lines.append(
                f"⚠️ **{self.waiting_escalations} open escalation"
                f"{'s' if self.waiting_escalations != 1 else ''}** waiting for your "
                f"answer — `operator_answer(escalation_id, decision)` then "
                f"`operator_resume(run_id)`."
            )
            lines.append("")
        lines.append(f"**Next move:** {self.next_action}")
        return "\n".join(lines)


def _run_signal(store: Any) -> tuple[int, int]:
    """(any_runs, execute_runs) read fail-soft straight from operator_runs.

    any_runs    — total operator runs for this agent (dry-run OR execute) → step 4.
    execute_runs — runs with a worktree (real `claude -p` drive) → step 5.

    Returns (-1, -1) if the table genuinely can't be read, so callers can be honest
    about not knowing rather than asserting 'none'."""
    db_path = getattr(store, "db_path", None)
    agent_id = getattr(store, "agent_id", None)
    if not db_path:
        return (-1, -1)
    try:
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "operator_runs" not in tables:
                # No runs have ever been recorded → table not yet created. Honest 0.
                return (0, 0)
            if agent_id:
                total = conn.execute(
                    "SELECT COUNT(*) FROM operator_runs WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()[0]
                executed = conn.execute(
                    "SELECT COUNT(*) FROM operator_runs "
                    "WHERE agent_id=? AND worktree IS NOT NULL AND worktree<>''",
                    (agent_id,),
                ).fetchone()[0]
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM operator_runs"
                ).fetchone()[0]
                executed = conn.execute(
                    "SELECT COUNT(*) FROM operator_runs "
                    "WHERE worktree IS NOT NULL AND worktree<>''"
                ).fetchone()[0]
            return (int(total), int(executed))
        finally:
            conn.close()
    except Exception:
        return (-1, -1)


def compute_journey(store: Any) -> Journey:
    """Where you are across the 5 steps + the single next move. Never raises."""
    # --- readiness (also our early-stage next-action fallback) ---
    try:
        readiness = clone_readiness.compute(store)
    except Exception:
        readiness = clone_readiness.CloneReadiness(percent=0, next_action="")
    pct = int(getattr(readiness, "percent", 0) or 0)
    readiness_next = getattr(readiness, "next_action", "") or \
        "keep working — your decisions are captured automatically"

    # --- step 1: Create (shadow signal) ---
    # The clone shadows you via `episodes` (one per observed action) — the broad
    # corpus — plus narrower explicit decision_events. Count BOTH; the corpus
    # alone is enough to lock step 1.
    try:
        counts = store.get_decision_event_counts() or {}
    except Exception:
        counts = {}
    total_events = sum(int(v) for v in counts.values())
    try:
        episodes = int(store.count_episodes())
    except Exception:
        episodes = 0

    # --- profile (steps 1 thin/2) ---
    has_profile = False
    try:
        has_profile = store.get_latest_operator_profile() is not None
    except Exception:
        has_profile = False

    # --- review coverage (step 2) ---
    coverage_pct = 0
    try:
        review = profile_review.review(store, use_llm=False)
        coverage_pct = int(getattr(review, "coverage_pct", 0) or 0)
    except Exception:
        coverage_pct = 0
    review_done = has_profile and coverage_pct > 0

    # --- practices (step 3) ---
    try:
        active_practices = store.get_practices(active_only=True)
    except Exception:
        active_practices = []
    n_practices = len(active_practices)

    # --- run history (steps 4 & 5) ---
    any_runs, execute_runs = _run_signal(store)

    # --- open escalations ---
    try:
        waiting = len(store.get_open_escalations(None) or [])
    except Exception:
        waiting = 0

    # ── Stage statuses ───────────────────────────────────────────────────────
    stages: list[Stage] = []

    # 1. Create
    if episodes >= _CREATE_DONE_EPISODES or total_events >= _CREATE_DONE_EVENTS:
        s1_status = "done"
        s1_detail = f"{episodes:,} episodes shadowed + {total_events} explicit decisions"
    elif has_profile or episodes > 0 or total_events > 0:
        s1_status = "active"
        s1_detail = (f"{episodes:,} episodes + {total_events} decisions so far — "
                     f"keep coding to thicken the signal")
    else:
        s1_status, s1_detail = "active", "just starting — Sentigent shadows your work"
    stages.append(Stage(1, _STAGE_NAMES[1], s1_status, s1_detail))
    s1_done = s1_status == "done"

    # 2. Review
    if review_done:
        s2_status = "done"
        s2_detail = f"reviewed — {coverage_pct}% best-practice coverage"
    elif s1_done or has_profile:
        s2_status = "active"
        s2_detail = ("run `clone_review` to see your good / bad / gaps"
                     if not has_profile else
                     f"profile built ({coverage_pct}% coverage) — run `clone_review`")
    else:
        s2_status, s2_detail = "locked", "unlocks once your clone has real signal"
    stages.append(Stage(2, _STAGE_NAMES[2], s2_status, s2_detail))

    # 3. Improve
    if n_practices >= 1:
        s3_status = "done"
        s3_detail = (f"{n_practices} practice{'s' if n_practices != 1 else ''} "
                     f"adopted into your playbook")
    elif review_done:
        s3_status = "active"
        s3_detail = "adopt a gap: `clone_adopt(1)` (or `scripts/practice.py add ...`)"
    else:
        s3_status, s3_detail = "locked", "unlocks after your first review"
    stages.append(Stage(3, _STAGE_NAMES[3], s3_status, s3_detail))
    s3_done = s3_status == "done"

    # 4. Reverse shadow (dry-run history)
    if any_runs > 0:
        s4_status = "done"
        s4_detail = (f"{any_runs} operator run{'s' if any_runs != 1 else ''} watched "
                     f"in dry-run")
    elif s3_done:
        s4_status = "active"
        if any_runs < 0:
            s4_detail = ("watch your clone judge a plan: `operator_preview.py <plan>` "
                         "(run history not readable, so can't confirm past runs)")
        else:
            s4_detail = ("watch your clone judge a plan: `operator_preview.py <plan>` "
                         "or `operator_start(goal=...)` (dry-run)")
    else:
        s4_status, s4_detail = "locked", "unlocks once you've adopted a practice"
    stages.append(Stage(4, _STAGE_NAMES[4], s4_status, s4_detail))
    s4_active_or_done = s4_status in ("active", "done")

    # 5. Fly mode (real execute history)
    if execute_runs > 0:
        s5_status = "done"
        s5_detail = (f"{execute_runs} real run{'s' if execute_runs != 1 else ''} "
                     f"flown — your clone has executed for you")
    elif s4_active_or_done:
        s5_status = "active"
        s5_detail = ("fly a tiny real task: `operator_start(goal=..., execute=True)` "
                     "in a throwaway branch")
    else:
        s5_status, s5_detail = "locked", "unlocks once your clone is reverse-shadowing"
    stages.append(Stage(5, _STAGE_NAMES[5], s5_status, s5_detail))

    # ── current stage = first not 'done' ────────────────────────────────────
    current = 5
    for s in stages:
        if s.status != "done":
            current = s.num
            break
    else:
        current = 5  # all done → keep flying

    # ── next action: readiness hint for early rungs, stage-specific later ────
    next_by_stage = {
        2: "run `clone_review` to see your clone's good, bad, and gaps",
        3: "adopt your first best practice — `clone_adopt(1)`",
        4: "run `operator_preview` on a plan to watch your clone judge as you",
        5: "`operator_start(goal=..., execute=True)` on a small real task",
    }
    if current == 1:
        next_action = readiness_next
    elif waiting:
        next_action = (f"answer your {waiting} open escalation"
                       f"{'s' if waiting != 1 else ''}: "
                       f"`operator_answer(id, decision)` then `operator_resume(run_id)`")
    else:
        next_action = next_by_stage.get(current, readiness_next)

    return Journey(
        readiness_pct=pct,
        current_stage=current,
        stages=stages,
        next_action=next_action,
        waiting_escalations=waiting,
    )
