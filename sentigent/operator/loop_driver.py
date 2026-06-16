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


# ── durable state (atomic) ────────────────────────────────────────────────────
def _state_path(loop_id: str) -> Path:
    return LOOP_DIR / f"{loop_id}.json"


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
def start(goal: str, steps: list[str], cwd: str = ".", *, verify_cmd: str = "",
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
        "steps": [
            {"i": i, "text": s, "status": "pending", "attempts": 0, "resolve_pushes": 0,
             "verified": None, "asked": False, "last_error": "", "clone_note": "",
             "result": "", "ended_at": None}
            for i, s in enumerate(steps)
        ],
        "history": [],
    }
    _save(state)
    return state


def _anchor_text(state: dict) -> str:
    out = []
    for f in state.get("anchor_files", []):
        p = Path(state["cwd"]) / f
        if p.exists():
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
    parts.append(f"YOUR STEP NOW (do ONLY this, then stop):\n  {step['text']}\n"
                 f"When complete, end your turn. Be concise.")
    return "\n\n".join(parts)


def _run_claude(prompt: str, cwd: str, timeout: int) -> tuple[bool, str]:
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
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


def _verify(state: dict, timeout: int = 600) -> tuple[bool, str]:
    """Closed-loop gate. Returns (passed, output_tail). No verify_cmd → trust the step."""
    cmd = state.get("verify_cmd", "")
    if not cmd:
        return True, ""
    try:
        r = subprocess.run(cmd, cwd=state["cwd"], shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return (r.returncode == 0), (r.stdout + r.stderr)[-600:]
    except Exception as e:
        return False, f"verify error: {e}"


def _resolver_worker(step: dict, budget: float, q) -> None:
    """Run the CloneResolver in a CHILD PROCESS (so a stuck model load can be killed —
    threads can't be). Puts (action, decision, rationale) on the queue; ask on failure."""
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
        resolver = CloneResolver(profile, store=store)
        res = resolver.resolve({
            "step_text": step["text"], "trigger": "verify_failed",
            "gate_reason": step.get("last_error", "")[:300],
            "risk_level": "medium", "category": "normal",
        })
        thr = CloneResolver.thresholds_from_calibration(store)
        if CloneResolver.should_apply(res, policy_wall=False, category="normal", thresholds=thr):
            if res.decision == APPROVE:
                q.put(("push", res.decision, res.rationale)); return
            if res.decision == SKIP:
                q.put(("skip", res.decision, res.rationale)); return
        q.put(("ask", res.decision, res.rationale))
    except Exception as e:
        q.put(("ask", "needs_human", f"clone unavailable ({e})"))


def _decide_blocker(state: dict, step: dict) -> tuple[str, str, str]:
    """Learned push-vs-ask at a real blocker — Sentigent's wedge over a bare Ralph loop.

    Asks the CloneResolver "what would you do here?" with learned per-category thresholds
    from your override history, under a HARD wall-clock budget (the clone answers fast or
    we page you — a loop that stalls minutes on a cold model load is worse than one that
    asks). Fail-soft to 'ask' so it NEVER fabricates autonomy."""
    if os.environ.get("SENTIGENT_LOOP_RESOLVER", "1") != "1":
        return "ask", "needs_human", "resolver disabled"
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
            return "ask", "needs_human", "clone timed out"
        try:
            return q.get_nowait()
        except Exception:
            return "ask", "needs_human", "clone returned nothing"
    except Exception as e:
        return "ask", "needs_human", f"resolver unavailable ({e})"


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
    step["attempts"] += 1
    if execute:
        ran_ok, result = _run_claude(prompt, state["cwd"], timeout)
        verified, vtail = _verify(state) if ran_ok else (False, result)
    else:
        ran_ok, result = True, f"DRY-RUN: would run `claude -p` for: {step['text']}"
        verified, vtail = _verify(state)          # dry-run still honors the verify gate

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
            action, decision, why = _decide_blocker(state, step)
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


if __name__ == "__main__":
    main()
