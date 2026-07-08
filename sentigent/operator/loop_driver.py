"""Cross-session loop driver — keep pushing a vision's plan after the session ends.

This is the loop-engineering core (see docs/LOOP-ENGINEERING.md). An OUTER driver
that survives the death of any single Claude Code session: the agent forgets when a
session ends; the loop state on disk remembers. Each lap:

  1. read the next step + anchor files (fresh context — the Ralph discipline)
  2. run a FRESH `claude -p` over just that step (failure from last lap piped in)
  3. CLOSED-LOOP VERIFY (tests/typecheck/lint); a failing step retries with the error
  4. STOP checks: plan done? · no-progress (same step fails N×)? · max laps? · budget?
  5. ATOMICALLY persist → the next step is durably queued before this session ends

If the driver process is killed mid-plan, `resume(loop_id)` picks up at the stored
step. Nothing is lost; the plan keeps moving.

OUTPUT METRIC — Faithful Autonomous Progress (FAP), the dark-factory KPI:
  distance = steps done / total           (how long it ran)
  fidelity = steps verified / steps done  (how faithfully — didn't drift/break)
  autonomy = blockers self-resolved / faced
  FAP      = verified-with-no-help / total   (one honest number, 0..1)
  faithful_streak = longest unbroken run of verified steps with no human ask

CLI:
  python -m sentigent.operator.loop_driver start  --goal "..." --steps "a" "b" [--verify "pytest -q"] [--anchor VISION.md]
  python -m sentigent.operator.loop_driver drive  <loop_id> [--execute] [--max N]
  python -m sentigent.operator.loop_driver resume <loop_id> [--execute]
  python -m sentigent.operator.loop_driver status <loop_id>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

LOOP_DIR = Path(os.environ.get("SENTIGENT_LOOP_DIR", str(Path.home() / ".sentigent" / "loops")))
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
# TRUST BOUNDARY: a cross-session loop runs `claude -p` headlessly, so by default it
# skips permission prompts (an interactive prompt would hang the loop forever — the whole
# point is unattended progress). This means the inner agent can run arbitrary shell in
# `cwd`. Run loops only on plans/repos you trust, ideally in an isolated checkout/worktree,
# and turn on guardrails (`guardrails=True` or SENTIGENT_LOOP_GUARDRAILS=1) for per-lap
# safety. Set SENTIGENT_LOOP_SKIP_PERMISSIONS=0 to force the agent's normal permission
# prompts (safer, but only usable when a human is present to answer them).
SKIP_PERMS = os.environ.get("SENTIGENT_LOOP_SKIP_PERMISSIONS", "1") == "1"


# ── durable state (atomic) ────────────────────────────────────────────────────
_LOOP_ID_RE = __import__("re").compile(r"^loop_[0-9a-f]{6,16}$")


def _state_path(loop_id: str) -> Path:
    # loop_id is attacker-controllable over MCP — validate strictly, then confirm the
    # resolved path can't escape LOOP_DIR (defense-in-depth against path traversal).
    if not _LOOP_ID_RE.match(loop_id or ""):
        raise ValueError(f"invalid loop_id: {loop_id!r}")
    p = (LOOP_DIR / f"{loop_id}.json").resolve()
    try:
        p.relative_to(LOOP_DIR.resolve())
    except ValueError:
        raise ValueError(f"loop_id escapes loop dir: {loop_id!r}")
    return p


def _save(state: dict) -> None:
    """Atomic write — a crash mid-save never corrupts the loop's memory."""
    LOOP_DIR.mkdir(parents=True, exist_ok=True)
    p = _state_path(state["loop_id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, p)  # atomic on POSIX


def load(loop_id: str) -> dict:
    p = _state_path(loop_id)
    if not p.exists():
        raise SystemExit(f"no such loop: {loop_id} (looked in {LOOP_DIR})")
    return json.loads(p.read_text())


# ── lifecycle ─────────────────────────────────────────────────────────────────
def _mk_step(i: int, s) -> dict:
    """A step is a string OR {text, verify}. A per-step `verify` (even "") overrides
    the loop's global verify_cmd — so each step has its OWN done-criteria, which is the
    honest way to gate (a 'write code' step ≠ a 'tests pass' step)."""
    text = s.get("text", "") if isinstance(s, dict) else str(s)
    step = {"i": i, "text": text, "status": "pending", "attempts": 0, "resolve_pushes": 0,
            "verified": None, "asked": False, "last_error": "", "clone_note": "",
            "result": "", "ended_at": None}
    if isinstance(s, dict) and "verify" in s:
        step["verify"] = str(s["verify"])
    return step


def start(goal: str, steps: list, cwd: str = ".", *, verify_cmd: str = "",
          anchor_files: list[str] | None = None, max_attempts: int = 3,
          max_resolve_pushes: int = 2, guardrails: bool = False,
          stamp: float | None = None) -> dict:
    loop_id = "loop_" + uuid.uuid4().hex[:8]
    state = {
        "loop_id": loop_id,
        "goal": goal,
        "cwd": str(Path(cwd).resolve()),
        "verify_cmd": verify_cmd,            # closed-loop gate (run after each step)
        "anchor_files": anchor_files or [],  # re-injected every lap (VISION/CLAUDE/...)
        "max_attempts": max_attempts,        # cheap retries before a fail is a real blocker
        "max_resolve_pushes": max_resolve_pushes,  # times the clone may push past a blocker
        "guardrails": guardrails,            # enforce org guardrail packs per lap (opt-in)
        "status": "running",                 # running | done | blocked | max | error
        "cursor": 0,
        "asks": 0,                           # times the loop had to page a human
        "clone_resolves": 0,                 # blockers the clone resolved (push/skip)
        "created_at": stamp or time.time(),
        "steps": [_mk_step(i, s) for i, s in enumerate(steps)],
        "history": [],
    }
    _save(state)
    return state


def _anchor_text(state: dict) -> str:
    files = state.get("anchor_files", [])
    if not files:
        return ""
    out = []
    root = Path(state["cwd"]).resolve()
    for f in files:
        # anchors may come from MCP — never read absolute paths, `..`, or anything that
        # resolves outside the loop's cwd.
        if not f or os.path.isabs(f) or ".." in Path(f).parts:
            continue
        p = (root / f).resolve()
        try:
            p.relative_to(root)
        except ValueError:
            continue
        if p.exists() and p.is_file():
            out.append(f"--- {f} ---\n{p.read_text()[:4000]}")
    return ("\n\n".join(out)) if out else ""


def _build_prompt(state: dict, step: dict) -> str:
    done = [s for s in state["steps"] if s["status"] == "done"]
    recap = "\n".join(f"  ✓ {s['text']}" for s in done) or "  (nothing yet)"
    anchors = _anchor_text(state)
    parts = [
        "You are one lap of an autonomous loop driving a plan toward a goal. You have a "
        "FRESH context — the notes below are your only memory.",
        f"GOAL:\n  {state['goal']}",
    ]
    if anchors:
        parts.append(f"ANCHOR DOCS (the vision/rules — stay faithful to these):\n{anchors}")
    parts.append(f"ALREADY DONE (previous laps):\n{recap}")
    if step["last_error"]:
        parts.append(f"⚠️ YOUR LAST ATTEMPT AT THIS STEP FAILED VERIFICATION:\n  {step['last_error'][:600]}\n"
                     f"Fix the cause this time.")
    gate = _step_gate(state, step)
    dod = f"\n  This step is DONE when this command passes: `{gate}`" if gate else ""
    parts.append(f"YOUR STEP NOW (do ONLY this, then stop):\n  {step['text']}{dod}\n"
                 f"When complete, end your turn. Be concise.")
    return "\n\n".join(parts)


def _run_claude(prompt: str, cwd: str, timeout: int) -> tuple[bool, str]:
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json"]
    if SKIP_PERMS:
        cmd.append("--dangerously-skip-permissions")  # headless autonomy; see TRUST BOUNDARY above
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except FileNotFoundError:
        return False, f"claude binary not found ({CLAUDE})"
    out = (r.stdout or "").strip()
    try:
        data = json.loads(out)
        if isinstance(data, list):
            res = [e for e in data if isinstance(e, dict) and e.get("type") == "result"]
            text = (res[-1].get("result") if res else "") or ""
        elif isinstance(data, dict):
            text = data.get("result", out)
        else:
            text = out
    except Exception:
        text = out
    return (r.returncode == 0), (text or "(no output)")[:2000]


def _verify(cwd: str, cmd: str, timeout: int = 600) -> tuple[bool, str]:
    """Closed-loop gate. Returns (passed, output_tail). Empty cmd → trust the step."""
    if not cmd:
        return True, ""
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return (r.returncode == 0), (r.stdout + r.stderr)[-600:]
    except Exception as e:
        return False, f"verify error: {e}"


def _step_gate(state: dict, step: dict) -> str:
    """Per-step verify command if the step defines one (even ''), else the global default."""
    return step["verify"] if "verify" in step else state.get("verify_cmd", "")


def _blocker_category(text: str) -> str:
    """Coarse, stable category for a blocker so calibration thresholds are learned
    per-kind (not one global bucket). Keyword buckets — honest and good enough."""
    t = (text or "").lower()
    for kw, cat in (("deploy", "deploy"), ("publish", "deploy"), ("migrat", "database"),
                    ("drop ", "database"), ("schema", "database"), ("secret", "secrets"),
                    (".env", "secrets"), ("push", "git"), ("merge", "git"),
                    ("test", "tests"), ("pytest", "tests"), ("install", "deps"),
                    ("delete", "destructive"), ("rm ", "destructive")):
        if kw in t:
            return cat
    return "general"


def _resolver_worker(step: dict, budget: float, q) -> None:
    """Run the CloneResolver in a CHILD PROCESS (so a stuck model load can be killed —
    threads can't be). Puts (action, decision, rationale, attempt) on the queue, where
    attempt = the clone's full guess {decision, confidence, category} — persisted on an
    'ask' so a later human answer can score it (calibration). Ask on failure."""
    try:
        # bind the resolver's model timeout BEFORE importing it (it reads the env at import)
        os.environ["SENTIGENT_RESOLVER_TIMEOUT"] = str(max(1, int(budget)))
        from sentigent.operator.resolver import CloneResolver, APPROVE, SKIP
        from sentigent.memory.store import MemoryStore
        agent = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
        org = os.environ.get("SENTIGENT_ORG_ID", agent)
        store = MemoryStore(agent_id=agent, org_id=org)
        profile = {}
        for getter in ("get_operator_profile", "get_profile"):
            fn = getattr(store, getter, None)
            if callable(fn):
                try:
                    profile = fn() or {}
                    break
                except Exception:
                    pass
        category = _blocker_category(step["text"])
        resolver = CloneResolver(profile, store=store)
        res = resolver.resolve({
            "step_text": step["text"], "trigger": "verify_failed",
            "gate_reason": step.get("last_error", "")[:300],
            "risk_level": "medium", "category": category,
        })
        attempt = {"decision": str(res.decision),
                   "confidence": float(getattr(res, "confidence", 0.0) or 0.0),
                   "category": category}
        thr = CloneResolver.thresholds_from_calibration(store)
        if CloneResolver.should_apply(res, policy_wall=False, category=category, thresholds=thr):
            if res.decision == APPROVE:
                q.put(("push", res.decision, res.rationale, attempt)); return
            if res.decision == SKIP:
                q.put(("skip", res.decision, res.rationale, attempt)); return
        q.put(("ask", res.decision, res.rationale, attempt))
    except Exception as e:
        q.put(("ask", "needs_human", f"clone unavailable ({e})", {}))


def _decide_blocker(state: dict, step: dict) -> tuple[str, str, str, dict]:
    """Learned push-vs-ask at a real blocker — Sentigent's wedge over a bare Ralph loop.

    Asks the CloneResolver "what would you do here?" with learned per-category thresholds
    from your override history, under a HARD wall-clock budget (the clone answers fast or
    we page you — a loop that stalls minutes on a cold model load is worse than one that
    asks). Fail-soft to 'ask' so it NEVER fabricates autonomy. Returns
    (action, decision, why, attempt) where attempt is the clone's scored guess."""
    if os.environ.get("SENTIGENT_LOOP_RESOLVER", "1") != "1":
        return "ask", "needs_human", "resolver disabled", {}
    budget = float(os.environ.get("SENTIGENT_LOOP_RESOLVE_TIMEOUT", "25"))
    try:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_resolver_worker, args=(step, budget, q), daemon=True)
        p.start()
        p.join(budget)
        if p.is_alive():
            p.terminate(); p.join(2)        # killable — no hang, ever
            return "ask", "needs_human", "clone timed out", {}
        try:
            return q.get_nowait()
        except Exception:
            return "ask", "needs_human", "clone returned nothing", {}
    except Exception as e:
        return "ask", "needs_human", f"resolver unavailable ({e})", {}


_GUARDRAIL_RULES = None


def _guardrail_check(text: str):
    """Org guardrail pack hit that should stop the lap for sign-off, else None. Fail-soft."""
    global _GUARDRAIL_RULES
    try:
        from sentigent.operator.guardrails import load_packs, evaluate
        if _GUARDRAIL_RULES is None:
            _GUARDRAIL_RULES = load_packs()
        d = evaluate(text, _GUARDRAIL_RULES)
        return d if d.stops_lap else None
    except Exception:
        return None


def _open_store():
    """Parent-side MemoryStore for escalation persistence + calibration. Fail-soft:
    returns None if the brain isn't importable so the loop never crashes on it."""
    try:
        from sentigent.memory.store import MemoryStore
        agent = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
        org = os.environ.get("SENTIGENT_ORG_ID", agent)
        return MemoryStore(agent_id=agent, org_id=org)
    except Exception:
        return None


def _persist_escalation(state: dict, step: dict, attempt: dict) -> int | None:
    """Record the blocker as an escalation carrying the clone's attempt, so a later
    human answer scores it (calibration). Returns escalation id or None (fail-soft)."""
    store = _open_store()
    if store is None:
        return None
    try:
        run_id = abs(hash(state["loop_id"])) % (10 ** 9)   # stable per-loop pseudo run id
        ctx = {"clone_attempt": attempt or {},
               "category": (attempt or {}).get("category", _blocker_category(step["text"])),
               "trigger": "loop_blocker", "loop_id": state["loop_id"], "step": step["i"]}
        return int(store.add_escalation(run_id, step["text"][:300], context=ctx,
                                        risk=0.5, step_id=step["i"]))
    except Exception:
        return None


def _find_blocked_step(state: dict) -> dict | None:
    """Return the step `answer()` would reopen for this loop's current blocker — the
    ONE selection rule shared by `answer()` and `list_pending_escalations()`, so the
    console listing can never drift from what answering actually resolves.

    Prefer the step at `open_escalation_step` (the normal "ask" path, set once
    `_persist_escalation` succeeds). When that's unset — the guardrail-check branch
    in `step_once()` never sets it, and neither does the ask branch when
    `_persist_escalation` fails/returns None — fall back to whichever step is
    `status == "failed"`. Both shapes still page a human via `state["status"] ==
    "blocked"`; only the escalation-store bookkeeping differs."""
    sidx = state.get("open_escalation_step")
    for s in state.get("steps", []):
        if (sidx is not None and s["i"] == sidx) or (sidx is None and s["status"] == "failed"):
            return s
    return None


def answer(loop_id: str, decision: str) -> dict:
    """Answer a loop's open blocker AS the human. Records the precedent + scores the
    clone's attempt (record_calibration via learn_from_escalation_answer), closes the
    escalation, reopens the failed step, and sets the loop back to running so the next
    drive()/resume() continues. This is what makes the loop's judgment actually learn."""
    state = load(loop_id)
    eid = state.get("open_escalation_id")
    learned = {}
    store = _open_store()
    if eid and store is not None:
        try:
            learned = store.learn_from_escalation_answer(int(eid), decision) or {}
        except Exception as e:
            learned = {"learned": False, "reason": str(e)}
        try:
            store.answer_escalation(int(eid), decision)
        except Exception:
            pass
    # reopen the step the loop blocked on so the plan can continue
    step = _find_blocked_step(state)
    if step is not None:
        step["status"] = "pending"
        step["attempts"] = 0
        step["asked"] = False
    state.pop("open_escalation_id", None)
    state.pop("open_escalation_step", None)
    state["status"] = "running"
    state["history"].append({"answered": decision, "escalation": eid,
                             "calibrated": learned.get("calibrated", False)})
    _save(state)
    return {"loop_id": loop_id, "answer": decision, "learned": learned,
            "status": state["status"]}


def list_pending_escalations(loop_dir: Path | str | None = None) -> list[dict]:
    """One item per loop currently blocked on a human — the pending queue behind the
    dashboard's /api/escalations. A loop shows up here iff `status == "blocked"` AND
    `_find_blocked_step` can locate the step paging the human — the SAME predicate
    `answer()` uses to pick what to reopen, so this listing can't be stricter (or
    looser) than what answering actually resolves. That covers all three shapes
    `step_once()` can leave a blocked loop in: the normal "ask" path
    (`open_escalation_step` set), the guardrail-check path (status="blocked",
    step failed, no open_escalation_step), and an ask-path where
    `_persist_escalation` failed/returned None (same shape as guardrail). The moment
    `answer()` reopens the step, it disappears. Read straight from each loop's
    persisted state — same source of truth as `load()`/`status_line()`, no separate
    store. Item shape: {loop_id, step, title, blocker, asked_at}."""
    d = Path(loop_dir or LOOP_DIR)
    out: list[dict] = []
    if not d.exists():
        return out
    for f in sorted(d.glob("loop_*.json")):
        try:
            state = json.loads(f.read_text())
        except Exception:
            continue
        if state.get("status") != "blocked":
            continue
        step = _find_blocked_step(state)
        if step is None:
            continue
        out.append({
            "loop_id": state["loop_id"],
            "step": step["i"],
            "title": step.get("text", "")[:120],
            "blocker": step.get("last_error") or step.get("clone_note") or "blocked",
            "asked_at": step.get("ended_at"),
        })
    return out


def step_once(loop_id: str, execute: bool = False, timeout: int = 1800) -> dict:
    """Execute the next pending step, verify, persist. Failing steps retry (pressure
    cooker) until max_attempts → then halt as `blocked` (no-progress) and count an ask."""
    state = load(loop_id)
    if state["status"] != "running":
        return state
    step = next((s for s in state["steps"] if s["status"] == "pending"), None)
    if step is None:
        state["status"] = "done"
        _save(state)
        return state

    # Per-lap org guardrail invariant (opt-in): never dispatch a flagged step
    # autonomously — stop for sign-off. This is the "won't drive off a cliff" gate.
    if state.get("guardrails") or os.environ.get("SENTIGENT_LOOP_GUARDRAILS") == "1":
        g = _guardrail_check(step["text"])
        if g is not None:
            step["status"] = "failed"
            step["asked"] = True
            step["last_error"] = g.message
            step["clone_note"] = f"guardrail:{g.rule_id} ({g.decision}) — {g.message}"[:300]
            state["asks"] += 1
            state["status"] = "blocked"
            state["history"].append({"step": step["i"], "guardrail": g.rule_id, "at": time.time()})
            _save(state)
            return state

    prompt = _build_prompt(state, step)
    gate = _step_gate(state, step)                # this step's OWN done-criteria
    step["attempts"] += 1
    if execute:
        ran_ok, result = _run_claude(prompt, state["cwd"], timeout)
        verified, vtail = _verify(state["cwd"], gate) if ran_ok else (False, result)
    else:
        ran_ok, result = True, f"DRY-RUN: would run `claude -p` for: {step['text']}"
        verified, vtail = _verify(state["cwd"], gate)   # dry-run still honors the gate

    step["result"] = result
    step["ended_at"] = time.time()
    ok = ran_ok and verified
    step["verified"] = verified if ran_ok else False

    if ok:
        step["status"] = "done"
        step["last_error"] = ""
        state["cursor"] = step["i"] + 1
    else:
        step["last_error"] = (vtail or result)[:600]
        if step["attempts"] < state["max_attempts"]:
            pass                                  # cheap retry next lap — pressure cooker
        else:
            # real blocker → LEARNED push-vs-ask (the wedge over raw Ralph)
            action, decision, why, attempt = _decide_blocker(state, step)
            step["clone_note"] = f"{decision}: {why}"[:300]
            if action == "push" and step["resolve_pushes"] < state["max_resolve_pushes"]:
                step["resolve_pushes"] += 1
                step["attempts"] = 0              # clone says keep going → fresh budget
                state["clone_resolves"] += 1
            elif action == "skip":
                step["status"] = "skipped"        # clone says move on
                state["clone_resolves"] += 1
                state["cursor"] = step["i"] + 1
            else:                                 # ask (or exhausted pushes) → page the human
                step["status"] = "failed"
                step["asked"] = True
                state["asks"] += 1
                state["status"] = "blocked"
                # G1: persist the clone's attempt as an escalation so the human's later
                # answer (loop_answer) can SCORE it → record_calibration. Without this the
                # loop is calibration-blind: thresholds never learn from real outcomes.
                eid = _persist_escalation(state, step, attempt)
                if eid:
                    state["open_escalation_id"] = eid
                    state["open_escalation_step"] = step["i"]

    state["history"].append({"step": step["i"], "attempt": step["attempts"],
                             "ok": ok, "at": step["ended_at"]})
    if state["status"] == "running" and all(s["status"] in ("done", "skipped") for s in state["steps"]):
        state["status"] = "done"
    _save(state)                              # next step durably queued
    return state


def drive(loop_id: str, execute: bool = False, max_steps: int = 50, timeout: int = 1800) -> dict:
    """Run laps until done/blocked/max. Each lap persists before the next, so killing
    this process and calling resume(loop_id) continues from the stored step."""
    state = load(loop_id)
    ran = 0
    while state["status"] == "running" and ran < max_steps:
        cur = next((s for s in state["steps"] if s["status"] == "pending"), None)
        state = step_once(loop_id, execute=execute, timeout=timeout)
        ran += 1
        if cur is not None:
            s = state["steps"][cur["i"]]
            mark = {"done": "✓", "pending": "…retry", "skipped": "↷ skipped"}.get(
                s["status"], "✗ blocked")
            print(f"  [{loop_id}] lap {ran}: {mark} {s['text'][:55]}")
    if state["status"] == "running" and ran >= max_steps:
        state["status"] = "max"
        _save(state)
    return state


def resume(loop_id: str, execute: bool = False, max_steps: int = 50, timeout: int = 1800) -> dict:
    """Continue after a session/process death — reads the stored cursor."""
    state = load(loop_id)
    if state["status"] in ("blocked", "max"):
        # clear the last failure so the retried step gets a fresh attempt budget
        for s in state["steps"]:
            if s["status"] == "failed":
                s["status"] = "pending"; s["attempts"] = 0; s["asked"] = False
                s["resolve_pushes"] = 0   # fresh push budget on human-triggered resume
        state["status"] = "running"
        _save(state)
    return drive(loop_id, execute=execute, max_steps=max_steps, timeout=timeout)


# ── THE output metric: Faithful Autonomous Progress ───────────────────────────
def metrics(state: dict) -> dict:
    steps = state["steps"]
    total = len(steps) or 1
    done = [s for s in steps if s["status"] == "done"]
    skipped = [s for s in steps if s["status"] == "skipped"]
    progressed = done + skipped                                     # the loop moved past these
    verified = [s for s in done if s.get("verified")]
    asks = state.get("asks", 0)
    resolves = state.get("clone_resolves", 0)
    faced = asks + resolves
    best = streak = 0
    for s in steps:
        if s["status"] == "done" and s.get("verified") and not s.get("asked"):
            streak += 1; best = max(best, streak)
        else:
            streak = 0
    return {
        "plan_distance": round(len(progressed) / total, 3),         # how long it ran
        "fidelity": round(len(verified) / len(progressed), 3) if progressed else 0.0,  # how faithfully
        "autonomy": round(resolves / faced, 3) if faced else 1.0,   # self-resolved vs paged you
        "FAP": round(len(verified) / total, 3),                     # the headline (0..1)
        "faithful_streak": best,
        "verified_steps": f"{len(verified)}/{len(steps)}",
        "skipped": len(skipped),
        "human_asks": asks,
        "clone_resolves": resolves,
    }


def _fap_sparkline(values: list[float]) -> str:
    """Unicode sparkline of FAP (0..1) across runs in chronological order."""
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(len(blocks) - 1, int(round(v * (len(blocks) - 1))))] for v in values)


def _fap_trend(rows: list[dict]) -> dict:
    """Is the loop getting smarter? Compare FAP of the earlier half of runs to the
    later half, in chronological order. This is the one number for 'the system
    compounds.' Honest: with too few runs there is no trend to report yet."""
    faps = [r["FAP"] for r in rows]
    out = {"n": len(rows), "sparkline": _fap_sparkline(faps),
           "early_mean": None, "late_mean": None, "delta": None, "verdict": ""}
    if len(rows) < 4:
        out["verdict"] = f"insufficient data — need ≥4 runs to show a trend (have {len(rows)})"
        return out
    half = len(faps) // 2
    early = round(sum(faps[:half]) / half, 3)
    late = round(sum(faps[half:]) / (len(faps) - half), 3)
    out["early_mean"], out["late_mean"], out["delta"] = early, late, round(late - early, 3)
    out["verdict"] = ("compounding ↑" if out["delta"] > 0.01
                      else "flat →" if out["delta"] >= -0.01 else "regressing ↓")
    return out


def receipt(loop_dir: Path | str | None = None) -> dict:
    """Aggregate FAP across every loop on disk — the dark-factory scoreboard.

    Real numbers only: each row is computed from that loop's own persisted state.
    Rows are ordered chronologically (by created_at) so the FAP trend is meaningful."""
    d = Path(loop_dir or LOOP_DIR)
    rows = []
    if d.exists():
        for f in d.glob("loop_*.json"):
            try:
                st = json.loads(f.read_text())
            except Exception:
                continue
            m = metrics(st)
            rows.append({"loop_id": st["loop_id"], "goal": st.get("goal", "")[:38],
                         "status": st.get("status", "?"),
                         "created_at": st.get("created_at", 0), **m})
    rows.sort(key=lambda r: r["created_at"])          # chronological → trend is honest
    n = len(rows) or 1
    agg = {
        "loops": len(rows),
        "mean_FAP": round(sum(r["FAP"] for r in rows) / n, 3),
        "mean_distance": round(sum(r["plan_distance"] for r in rows) / n, 3),
        "mean_fidelity": round(sum(r["fidelity"] for r in rows) / n, 3),
        "total_asks": sum(r["human_asks"] for r in rows),
        "total_clone_resolves": sum(r["clone_resolves"] for r in rows),
        "completed": sum(1 for r in rows if r["status"] == "done"),
        "fap_trend": _fap_trend(rows),               # is the system getting smarter?
    }
    return {"rows": rows, "aggregate": agg}


def print_receipt(loop_dir: Path | str | None = None) -> None:
    rep = receipt(loop_dir)
    a = rep["aggregate"]
    print("━" * 72)
    print("  SENTIGENT LOOP RECEIPT — Faithful Autonomous Progress across runs")
    print("━" * 72)
    print(f"  {'loop':<14}{'FAP':>6}{'dist':>6}{'fid':>6}{'auto':>6}{'asks':>6}  goal")
    print("  " + "─" * 68)
    for r in rep["rows"]:
        print(f"  {r['loop_id']:<14}{r['FAP']:>6.0%}{r['plan_distance']:>6.0%}"
              f"{r['fidelity']:>6.0%}{r['autonomy']:>6.0%}{r['human_asks']:>6}  {r['goal']}")
    print("  " + "─" * 68)
    print(f"  {a['loops']} loops · {a['completed']} completed · mean FAP {a['mean_FAP']:.0%} · "
          f"mean distance {a['mean_distance']:.0%} · mean fidelity {a['mean_fidelity']:.0%}")
    print(f"  clone-resolved {a['total_clone_resolves']} blocker(s) · paged you {a['total_asks']}× total")
    t = a["fap_trend"]
    if t["sparkline"]:
        line = f"  FAP over time  {t['sparkline']}  "
        if t["delta"] is not None:
            line += f"{t['early_mean']:.0%} → {t['late_mean']:.0%}  ({t['verdict']})"
        else:
            line += t["verdict"]
        print("  " + "─" * 68)
        print(line)
    print("━" * 72)


def status_line(state: dict) -> str:
    m = metrics(state)
    icon = {"running": "▶", "done": "✅", "blocked": "⏸", "max": "🔁", "error": "🛑"}.get(state["status"], "•")
    nxt = next((s["text"] for s in state["steps"] if s["status"] == "pending"), "—")
    return (
        f"{icon} {state['loop_id']}  {state['status']}\n"
        f"  goal: {state['goal']}\n"
        f"  next: {nxt}\n"
        f"  ── Faithful Autonomous Progress ──\n"
        f"  FAP {m['FAP']:.0%}   distance {m['plan_distance']:.0%}   fidelity {m['fidelity']:.0%}   "
        f"autonomy {m['autonomy']:.0%}\n"
        f"  verified {m['verified_steps']} · faithful streak {m['faithful_streak']} · "
        f"clone-resolved {m['clone_resolves']} · paged you {m['human_asks']}×"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="cross-session loop driver (dark factory)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--goal", required=True)
    s.add_argument("--steps", nargs="+", required=True); s.add_argument("--cwd", default=".")
    s.add_argument("--verify", default=""); s.add_argument("--anchor", nargs="*", default=[])
    s.add_argument("--max-attempts", type=int, default=3)
    for name in ("drive", "resume"):
        p = sub.add_parser(name); p.add_argument("loop_id")
        p.add_argument("--execute", action="store_true"); p.add_argument("--max", type=int, default=50)
    st = sub.add_parser("status"); st.add_argument("loop_id")
    sub.add_parser("receipt")
    a = ap.parse_args()

    if a.cmd == "start":
        state = start(a.goal, a.steps, a.cwd, verify_cmd=a.verify, anchor_files=a.anchor,
                      max_attempts=a.max_attempts)
        print(status_line(state))
        print(f"\ndrive it:  python -m sentigent.operator.loop_driver drive {state['loop_id']} --execute")
    elif a.cmd in ("drive", "resume"):
        fn = drive if a.cmd == "drive" else resume
        print(status_line(fn(a.loop_id, execute=a.execute, max_steps=a.max)))
    elif a.cmd == "status":
        print(status_line(load(a.loop_id)))
    elif a.cmd == "receipt":
        print_receipt()


if __name__ == "__main__":
    main()
