#!/usr/bin/env python3
"""Sentigent hook — closes the feedback loop automatically.

PreToolUse:  evaluates the action, saves trace_id to a temp file.
             Also checks learned failure patterns to proactively suggest
             MCP alternatives before a Bash command is attempted.
PostToolUse: reads the trace_id, records outcome from exit code / test output.
             On Bash failures, surfaces an MCP alternative as a message to Claude.

This is what makes Sentigent actually learn — without outcomes,
all episodes are useless observations with no signal.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ── Shared state between pre/post (same machine, sequential calls) ──────────
_TRACE_FILE = Path("/tmp/sentigent_last_trace.json")

# Recompute baselines every N outcomes so signals start changing fast
_BASELINE_EVERY = 5

# ── Bash failure tracking (persisted across hook calls) ──────────────────────
_BASH_FAIL_FILE = Path("/tmp/sentigent_bash_failures.json")

# ── Tool categories ──────────────────────────────────────────────────────────
_SAFE_TOOLS = {"Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "Task",
               "NotebookRead", "TodoRead", "TaskList", "TaskGet"}

# ── Test runner detection ────────────────────────────────────────────────────
_TEST_CMD_RE = re.compile(
    r"\b(pytest|python\s+-m\s+pytest|npm\s+(run\s+)?test|yarn\s+(run\s+)?test"
    r"|pnpm\s+(run\s+)?test|jest|vitest|cargo\s+test|go\s+test|mocha"
    r"|rspec|minitest|phpunit|dotnet\s+test|mvn\s+test|gradle\s+test)\b"
)

# Patterns in output that mean tests FAILED
_FAIL_RE = re.compile(
    r"(\d+\s+failed|FAILED|FAIL\b|AssertionError|Tests:\s+\d+\s+failed"
    r"|error\[E\d+\]|ERRORS|test result: FAILED)",
    re.IGNORECASE,
)

# Patterns in output that mean tests PASSED
_PASS_RE = re.compile(
    r"(\d+\s+passed|All tests passed|Tests:\s+\d+\s+passed"
    r"|\bOK\b|test result: ok|PASS\b|passing)",
    re.IGNORECASE,
)

# Patterns in Bash output that signal a command-level failure
_CMD_FAIL_RE = re.compile(
    r"(Error:|error:|command not found|No such file|Permission denied"
    r"|exit status [1-9]|returned non-zero|ENOENT|EACCES|fatal:|Exception:)",
    re.IGNORECASE,
)


# ── Session-start routing (M2) ────────────────────────────────────────────────
_SESSION_DIR = Path("/tmp/sentigent_sessions")
_SESSION_DIR.mkdir(exist_ok=True)


def _get_session_file() -> Path:
    """One temp file per Claude Code session (keyed to parent process PID)."""
    ppid = str(os.getppid())
    return _SESSION_DIR / f"session_{ppid}.json"


def _is_first_call_this_session() -> bool:
    """True only the first time this hook runs in this OS process tree."""
    sf = _get_session_file()
    if sf.exists():
        return False
    sf.write_text("{}")
    return True


def _run_session_start_routing(task_text: str) -> None:
    """Fire sentigent_route + sentigent_intent on session start; log to session file."""
    try:
        import subprocess
        import sys as _sys_inner
        _project_root = str(Path(__file__).parent.parent.parent)
        result = subprocess.run(
            [_sys_inner.executable, "-c",
             f"""
import json, sys, os
sys.path.insert(0, {repr(_project_root)})
os.environ.setdefault('SENTIGENT_AGENT_ID', os.environ.get('SENTIGENT_AGENT_ID', 'claude_code'))
os.environ.setdefault('SENTIGENT_PROFILE', os.environ.get('SENTIGENT_PROFILE', 'code_review'))
from sentigent.mcp_server import sentigent_route, sentigent_intent
route = json.loads(sentigent_route(task_text={repr(task_text[:200])}))
intent = json.loads(sentigent_intent(task={repr(task_text[:200])}))
print(json.dumps({{'route': route, 'intent': intent}}))
"""],
            capture_output=True, text=True, timeout=10,
            env={**os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            sf = _get_session_file()
            sf.write_text(result.stdout.strip())
    except Exception:
        pass


# ── Load .env for Supabase Layer 2 sync ──────────────────────────────────────
def _load_dotenv() -> None:
    """Load SUPABASE_* vars from sentigent .env so Layer 2 sync works in hooks."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key.startswith("SUPABASE_") and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


_load_dotenv()

# ── Singleton judge (one per hook process) ───────────────────────────────────
_judge = None


def _get_judge():
    global _judge
    if _judge is None:
        from sentigent.core.engine import Sentigent
        _judge = Sentigent(
            profile=os.environ.get("SENTIGENT_PROFILE", "code_review"),
            agent_id=os.environ.get("SENTIGENT_AGENT_ID", "hussain"),
        )
    return _judge


# ── Trace file helpers ────────────────────────────────────────────────────────
def _save_trace(trace_id: str, tool_name: str, task: str, routing_confidence: float = 0.0) -> None:
    try:
        _TRACE_FILE.write_text(json.dumps({
            "trace_id": trace_id,
            "tool_name": tool_name,
            "task": task,
            "routing_confidence": routing_confidence,
        }))
    except Exception:
        pass


def _load_trace() -> dict[str, str] | None:
    try:
        if _TRACE_FILE.exists():
            return json.loads(_TRACE_FILE.read_text())
    except Exception:
        pass
    return None


# ── Bash failure tracker ─────────────────────────────────────────────────────
def _record_bash_failure(command: str, error: str) -> None:
    """Persist Bash failure to a rolling JSON file for cross-call pattern detection."""
    try:
        from sentigent.core.bash_advisor import suggest_alternative
        import time

        failures: list[dict] = []
        if _BASH_FAIL_FILE.exists():
            try:
                failures = json.loads(_BASH_FAIL_FILE.read_text())
            except Exception:
                failures = []

        alt = suggest_alternative(command)
        failures.append({
            "ts": time.time(),
            "command": command[:120],
            "error": error[:120],
            "suggested_tool": alt.tool if alt else "mcp__desktop-commander",
        })
        # Keep last 50 failures
        failures = failures[-50:]
        _BASH_FAIL_FILE.write_text(json.dumps(failures))
    except Exception:
        pass


def _check_bash_failure_pattern(command: str) -> str | None:
    """Return a warning if this command has failed repeatedly before."""
    try:
        if not _BASH_FAIL_FILE.exists():
            return None
        failures = json.loads(_BASH_FAIL_FILE.read_text())
        # Look for the same command prefix in recent failures
        cmd_prefix = command.split()[0] if command.split() else ""
        if not cmd_prefix:
            return None
        recent = [f for f in failures if f.get("command", "").startswith(cmd_prefix)]
        if len(recent) >= 2:
            last = recent[-1]
            return (
                f"Sentigent: Bash({cmd_prefix}) has failed {len(recent)} times recently. "
                f"Last error: {last.get('error', '')[:80]}. "
                f"Consider using {last.get('suggested_tool', 'an MCP alternative')} instead."
            )
    except Exception:
        pass
    return None


# ── Baseline recompute trigger ────────────────────────────────────────────────
def _maybe_recompute(judge) -> None:
    """Recompute baselines periodically so signals start evolving."""
    try:
        stats = judge._memory.get_outcome_stats()
        total = sum(stats.values())
        if total > 0 and total % _BASELINE_EVERY == 0:
            judge._memory.update_baselines_from_episodes()
    except Exception:
        pass


# ── Context enrichment ────────────────────────────────────────────────────────
def _enrich(tool_name: str, tool_input: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {"tool_name": tool_name}

    if tool_name == "Bash":
        ctx["lines_changed"] = tool_input.count("\n")
        low = tool_input.lower()
        for dangerous in ("rm -rf", "rm -r", "drop table", "truncate",
                          "reset --hard", "push --force", "push -f", "--no-verify",
                          "format c:", "mkfs"):
            if dangerous in low:
                ctx["is_destructive"] = True
                ctx["consequence_severity"] = 0.9
                break
        if any(k in low for k in ("deploy", " push", "publish", "release")):
            ctx["is_deployment"] = True
        if _TEST_CMD_RE.search(tool_input):
            ctx["is_test_run"] = True

    elif tool_name in ("Write", "Edit"):
        ctx["lines_changed"] = tool_input.count("\n")
        low = tool_input.lower()
        for sensitive in (".env", "secret", "credential", "password", "private_key", "api_key"):
            if sensitive in low:
                ctx["is_sensitive_file"] = True
                ctx["consequence_severity"] = 0.8
                break

    return ctx


# ── Inline nudge (opt-in, rare, non-blocking) ─────────────────────────────────
# Surfaces a one-line reminder of a declared practice before a high-signal action
# (git commit / push). NEVER changes the approve/deny decision; emits nothing on
# any error; gated OFF by default behind SENTIGENT_INLINE_NUDGES so it can't
# surprise the user. Must add < a few ms and never raise.
_COMMIT_PUSH_RE = re.compile(r"\bgit\s+(commit|push)\b", re.IGNORECASE)


def _inline_nudge(tool_name: str, tool_input: str) -> str:
    """Return a short reminder string for a relevant declared practice, or ''.

    Opt-in (SENTIGENT_INLINE_NUDGES), fail-soft, decision-neutral.
    """
    try:
        if os.environ.get("SENTIGENT_INLINE_NUDGES", "0") not in ("1", "true", "on"):
            return ""
        if tool_name != "Bash" or not isinstance(tool_input, str):
            return ""
        if not _COMMIT_PUSH_RE.search(tool_input):
            return ""

        from sentigent.memory.store import MemoryStore

        agent_id = os.environ.get("SENTIGENT_AGENT_ID", "")
        org_id = os.environ.get("SENTIGENT_ORG_ID", "")
        store = MemoryStore(agent_id=agent_id, org_id=org_id)
        practices = store.get_practices(active_only=True)
        for p in practices:
            text = (p.get("text") or "").strip()
            low = text.lower()
            if "test" in low or "review" in low:
                return f"🧬 reminder: you hold '{text}' here."
        return ""
    except Exception:
        return ""


# ── Deterministic catastrophe guard ───────────────────────────────────────────
# High-precision, irreversible-only patterns. This does NOT depend on the learned
# judge (which historically never escalated on raw shell danger) — it always fires.
# Tuned to avoid false positives on normal dev work (e.g. `rm -rf node_modules` is
# allowed; `rm -rf /` / `~` / `$HOME` / wildcard is blocked).
def _catastrophic(cmd: str) -> str | None:
    import re
    raw = (cmd or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # Pipe-to-shell is judged on the WHOLE line (the pipe is the mechanism).
    if re.search(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?\w*sh\b", low):
        return "curl|sh — executing unverified remote code"
    if ":|:&" in raw.replace(" ", ""):
        return "fork bomb"

    # Everything else is judged PER SEGMENT so flags from one command don't bleed
    # into another (e.g. `git commit -F msg && git push` must not look like push -f).
    for seg in re.split(r"[;&|\n]+", raw):
        s = seg.strip()
        if not s:
            continue
        sl = s.lower()

        # recursive force-delete of a root / home / wildcard target
        if re.search(r"\brm\b", sl):
            has_r = bool(re.search(r"-\w*r", sl)) or "--recursive" in sl
            has_f = bool(re.search(r"-\w*f", sl)) or "--force" in sl
            if has_r and has_f:
                if ("--no-preserve-root" in sl
                        or re.search(r"(^|\s)(/|~|\$home|/\*|\*|\.\.)(\s|/|$)", sl)
                        or re.search(r"\s/(bin|etc|usr|var|lib|sys|boot|dev|opt|root|home)(\s|/|$)", sl)):
                    return "rm -rf on root/home/wildcard — irreversible mass deletion"

        # force-push (rewrites shared history). Case-SENSITIVE -f so `commit -F` is safe;
        # --force-with-lease is the safe variant and allowed.
        if re.search(r"\bgit\s+push\b", sl) and "--force-with-lease" not in sl:
            if "--force" in sl or re.search(r"(^|\s)-[A-Za-z]*f[A-Za-z]*\b", s):
                return "git push --force — rewrites shared remote history"

        # hard reset discards uncommitted work
        if re.search(r"\bgit\s+reset\b.*--hard", sl):
            return "git reset --hard — discards uncommitted changes"

        # destructive SQL — only when a SQL client runs it (so a commit message that
        # merely mentions DROP TABLE is not flagged).
        if re.search(r"\b(drop\s+(table|database|schema)|truncate\s+table)\b", sl):
            if re.search(r"\b(psql|mysql|mariadb|sqlite3|mongosh?|supabase|prisma)\b", sl) \
                    or re.match(r"^\s*(drop|truncate)\b", sl):
                return "destructive SQL (DROP / TRUNCATE)"

        # raw disk write / format
        if re.search(r"\bdd\b.*of=/dev/", sl) or re.search(r"\bmkfs(\.\w+)?\b.*/dev/", sl) \
                or re.search(r">\s*/dev/sd", sl):
            return "raw disk write/format — destroys a device"

        # recursive chmod on root
        if re.search(r"\bchmod\b.*-\w*r.*\s/(\s|$)", sl) or re.search(r"\bchmod\b.*\s777\s+/(\s|$)", sl):
            return "recursive chmod on / — breaks system permissions"

    return None


# ── Pre-hook ──────────────────────────────────────────────────────────────────
def pre_hook(tool_name: str, tool_input: str) -> dict[str, Any]:
    """Evaluate action before execution. Save trace_id for post-hook."""
    # Deterministic catastrophe guard — fires for Bash regardless of the learned
    # judge. This is the one guarantee a safety layer must make.
    if tool_name == "Bash" and isinstance(tool_input, str):
        danger = _catastrophic(tool_input)
        if danger:
            return {
                "decision": "block",
                "reason": (f"⛔ Sentigent safety guard: {danger}. This is irreversible — "
                           f"re-run only if you are certain, or narrow the command."),
            }

    if tool_name in _SAFE_TOOLS:
        # Clear trace file so post-hook knows to skip
        try:
            _TRACE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return {"decision": "approve"}

    # Session-start routing fires once per session (M2)
    if _is_first_call_this_session():
        raw_task = tool_input[:200] if isinstance(tool_input, str) else str(tool_input)[:200]
        _run_session_start_routing(raw_task)

    judge = _get_judge()
    ctx = _enrich(tool_name, tool_input)

    # ── Bash: warn before a repeated failure pattern ──
    if tool_name == "Bash":
        pattern_warning = _check_bash_failure_pattern(tool_input)
        if pattern_warning:
            ctx["has_prior_bash_failures"] = True

    decision = judge.evaluate(
        task=f"{tool_name}: {tool_input[:200]}",
        context=ctx,
        agent_state={},
    )

    _save_trace(decision.trace_id, tool_name, f"{tool_name}: {tool_input[:200]}", routing_confidence=decision.judgment_score)

    action = decision.action.value
    if action == "escalate":
        return {
            "decision": "block",
            "reason": f"Sentigent (score={decision.judgment_score:.0%}): {decision.reason}",
        }

    # Optional inline nudge (opt-in, rare, decision-neutral). Computed fail-soft;
    # appended to non-blocking approve messages only — never alters the decision.
    nudge = _inline_nudge(tool_name, tool_input)

    def _approve_with(*parts: str) -> dict[str, Any]:
        msg = " ".join(p for p in parts if p).strip()
        return {"decision": "approve", "message": msg} if msg else {"decision": "approve"}

    # Surface pattern warning (if any) alongside Sentigent's own message
    if tool_name == "Bash":
        pattern_warning = _check_bash_failure_pattern(tool_input)
        if pattern_warning:
            return _approve_with(pattern_warning, nudge)

    if action in ("slow_down", "enrich"):
        return _approve_with(f"Sentigent: {decision.reason}", nudge)
    return _approve_with(nudge)


# ── Post-hook ─────────────────────────────────────────────────────────────────
def post_hook(data: dict[str, Any]) -> dict[str, Any]:
    """Record outcome against the trace_id saved by pre_hook."""
    trace = _load_trace()
    if not trace:
        return {"decision": "approve"}

    trace_id = trace.get("trace_id", "")
    if not trace_id:
        return {"decision": "approve"}

    tool_name = data.get("tool_name", trace.get("tool_name", ""))
    raw_input = data.get("tool_input", {})
    tool_input = (
        raw_input.get("command", json.dumps(raw_input))
        if isinstance(raw_input, dict)
        else str(raw_input)
    )

    # tool_response can be a string or a dict {"output": ..., "error": ...}
    raw_response = data.get("tool_response", "")
    if isinstance(raw_response, dict):
        response_str = str(raw_response.get("output", ""))
        resp_error = raw_response.get("error") or data.get("error")
    else:
        response_str = str(raw_response)
        resp_error = data.get("error")

    outcome: str
    feedback: str

    # ── Bash ──
    if tool_name == "Bash":
        from sentigent.core.bash_advisor import is_bash_failure, format_advice

        tool_interrupted = bool(data.get("interrupted"))
        failed = is_bash_failure(response_str, resp_error, tool_interrupted)

        if failed:
            error_snippet = (
                str(resp_error)[:200] if resp_error
                else (response_str[:200] if response_str else "unknown error")
            )
            outcome = "incorrect"
            feedback = f"Bash failed: {error_snippet}"
            _record_bash_failure(tool_input, error_snippet)

            try:
                judge = _get_judge()
                judge.record_outcome(trace_id, outcome, feedback)
                _maybe_recompute(judge)
            except Exception:
                pass

            advice = format_advice(tool_input, error_snippet)
            return {
                "decision": "approve",
                "message": advice,
            }

        elif _TEST_CMD_RE.search(tool_input):
            combined = response_str
            if _FAIL_RE.search(combined):
                outcome = "incorrect"
                feedback = "Test run failed"
            elif _PASS_RE.search(combined):
                outcome = "correct"
                feedback = "Test run passed"
            else:
                outcome = "neutral"
                feedback = "Test run completed (result inconclusive)"

        elif _CMD_FAIL_RE.search(response_str):
            outcome = "incorrect"
            feedback = "Command output indicates failure"
            _record_bash_failure(tool_input, response_str[:200])

        else:
            # Phase 0 honest-foundation: "the command didn't error" is NOT a
            # judgment signal — it says nothing about whether the *decision* was
            # right. Mark neutral so it's excluded from judgment_score and
            # rule-mining (engine.py:722, store.py:859). Real outcome signal now
            # comes from decision_events (approve/deny/edit/undo). See
            # docs/plans/2026-06-03-operator-autopilot-design.md (G1/A1).
            outcome = "neutral"
            feedback = "Bash succeeded (no judgment signal)"

    # ── Write / Edit ──
    elif tool_name in ("Write", "Edit"):
        if resp_error:
            outcome = "incorrect"
            feedback = f"{tool_name} failed: {str(resp_error)[:200]}"
        else:
            # Phase 0 honest-foundation: a successful Write/Edit is not evidence
            # the decision was right (you may revert or redo it). Neutral.
            outcome = "neutral"
            feedback = f"{tool_name} applied (no judgment signal)"

    # ── Everything else ──
    else:
        # Phase 0 honest-foundation: only a real error is a known-bad signal;
        # mere completion is not a known-good one.
        outcome = "incorrect" if resp_error else "neutral"
        feedback = str(resp_error)[:200] if resp_error else "Tool completed (no judgment signal)"

    try:
        judge = _get_judge()
        judge.record_outcome(trace_id, outcome, feedback)
        _maybe_recompute(judge)
    except Exception:
        pass

    # ── Cost telemetry + Setup observation (shared store — one _init_db()) ────
    _shared_store = None
    try:
        from sentigent.memory.store import MemoryStore as _MemoryStore
        _agent_id = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
        _org_id = os.environ.get("SENTIGENT_ORG_ID", "default")
        _shared_store = _MemoryStore(agent_id=_agent_id, org_id=_org_id)
        _record_cost_event(data, trace_id, tool_name, store=_shared_store)
    except Exception:
        pass

    # ── Setup observation (M3) ────────────────────────────────────────────────
    if _shared_store is not None:
        try:
            from sentigent.setup.observer import SetupObserver as _SetupObserver
            _obs = _SetupObserver(_shared_store)
            _routing_conf = float(trace.get("routing_confidence", 0.0)) if trace else 0.0
            _exit_code_raw = data.get("exit_code")
            if isinstance(_exit_code_raw, (int, str)):
                try:
                    _exit_code: int | None = int(_exit_code_raw)
                except (ValueError, TypeError):
                    _exit_code = None
            else:
                _exit_code = None
            _obs.observe(
                tool_name=tool_name,
                tool_input=tool_input[:500],
                routing_confidence=_routing_conf,
                exit_code=_exit_code,
            )
        except Exception:
            pass

    # ── Decision capture (Phase 0, A1) — record a real REVERT preference signal.
    # A git revert/reset/checkout means prior work is being thrown away: an
    # unambiguous "that was wrong" signal, unlike the old "tool ran = correct".
    if _shared_store is not None and tool_name == "Bash":
        try:
            from sentigent.core.decision_capture import DecisionCapture as _DC
            _DC(_shared_store, _agent_id, _org_id).capture_bash_revert(
                tool_input, prior_trace_id=trace_id
            )
        except Exception:
            pass

    return {"decision": "approve"}


def _record_cost_event(
    data: dict[str, Any],
    trace_id: str,
    tool_name: str,
    store: "Any | None" = None,
) -> None:
    """Persist a cost event for this tool call using usage data from the hook payload.

    Args:
        data: Hook payload dict.
        trace_id: Trace ID for this call.
        tool_name: Name of the tool being called.
        store: Optional pre-constructed MemoryStore. If None, one is created internally.
    """
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    token_source = "usage"
    if input_tokens == 0 and output_tokens == 0:
        # Phase 0 real-cost: Claude Code's PostToolUse payload carries no usage
        # block, so the old code recorded $0.00 for every call (and fake $0
        # "savings"). Estimate from actual content sizes — a true lower-bound
        # proxy — and flag it so it's never presented as exact.
        from sentigent.telemetry.cost_tracker import estimate_tokens as _est
        _raw_in = data.get("tool_input", {})
        _in_text = json.dumps(_raw_in) if isinstance(_raw_in, dict) else str(_raw_in)
        _out_text = str(data.get("tool_response", ""))
        input_tokens = _est(_in_text)
        output_tokens = _est(_out_text)
        token_source = "estimated_from_io"
    model = (
        data.get("model")
        or os.environ.get("CLAUDE_MODEL", "")
        or os.environ.get("ANTHROPIC_MODEL", "sonnet")
    )

    from sentigent.telemetry.cost_tracker import build_cost_event

    agent_id = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    if store is None:
        from sentigent.memory.store import MemoryStore
        store = MemoryStore(agent_id=agent_id, org_id="default")
    event = build_cost_event(
        trace_id=trace_id,
        agent_id=agent_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_name=tool_name,
        meta={"token_source": token_source},
    )
    store.insert_cost_event(event.to_dict())


def prompt_hook(data: dict[str, Any]) -> dict[str, Any]:
    """UserPromptSubmit: capture the user's reaction to prior work as a
    decision_event (approve / reject / correct). Phase 0 DecisionCapture (A1).

    The single highest-value preference signal — the human reacting to what the
    agent just did. Fail-open: never blocks or alters the prompt (returns {}).
    """
    prompt = data.get("prompt", "") or ""
    try:
        from sentigent.core.decision_capture import DecisionCapture
        from sentigent.memory.store import MemoryStore

        agent_id = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
        org_id = os.environ.get("SENTIGENT_ORG_ID", "default")
        store = MemoryStore(agent_id=agent_id, org_id=org_id)
        trace = _load_trace() or {}
        DecisionCapture(store, agent_id, org_id).capture_prompt_reaction(
            prompt, prior_trace_id=trace.get("trace_id", "")
        )
    except Exception:
        pass
    return {}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        data = json.loads(sys.stdin.read())
        if mode == "pre":
            tool_name = data.get("tool_name", "")
            raw = data.get("tool_input", {})
            tool_input = (
                raw.get("command", json.dumps(raw))
                if isinstance(raw, dict)
                else str(raw)
            )
            result = pre_hook(tool_name, tool_input)
        elif mode == "prompt":
            result = prompt_hook(data)
        else:
            result = post_hook(data)
        print(json.dumps(result))
    except Exception:
        print(json.dumps({"decision": "approve"}))
