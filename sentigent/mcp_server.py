"""Sentigent MCP Server — exposes judgment tools via Model Context Protocol.

This is the universal interface that works with Claude Code, Cursor, Windsurf,
OpenAI Agents, and any other MCP-compatible client.

Run standalone:
    python -m sentigent.mcp_server

Or via uvx:
    uvx sentigent-mcp

Configure in Claude Code:
    claude mcp add sentigent -- python -m sentigent.mcp_server
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP server requires the 'mcp' package. Install with: pip install mcp"
    )

from sentigent.core.engine import Sentigent
from sentigent.core.types import DecisionAction
from sentigent.policies import check_policies, get_override_action, load_policies

# Initialize MCP server
mcp = FastMCP(name="Sentigent")

# ── Tool surface profile ──────────────────────────────────────────────────────
# The full server exposes 61 tools — far more than an agent can reason about
# (the 2026-07-07 principal review flagged this as tool sprawl). Setting
# SENTIGENT_TOOL_PROFILE=core registers only the 14 load-bearing tools: the
# judgment loop, the loop driver (the core product), and the operator's one
# answer hook. Default stays "full" so nothing breaks for existing installs.
_PROFILE = os.environ.get("SENTIGENT_TOOL_PROFILE", "full").lower()

CORE_TOOLS = frozenset({
    # Judgment loop. sentigent_record feeds the episodes that graded_score,
    # precedents, and baselines all depend on — omitting it would starve them.
    "sentigent_evaluate",
    "sentigent_record",
    "sentigent_outcome",
    "sentigent_feedback",
    "sentigent_score",
    "sentigent_patterns",
    "sentigent_policy",
    "sentigent_insights",
    "sentigent_review",
    # Loop driver — the core product. The full drive→ask→answer→resume cycle
    # must be present or a loop that blocks on a human decision dead-ends.
    "loop_start",
    "loop_drive",
    "loop_answer",
    "loop_resume",
    "loop_status",
    "loop_receipt",
    # Operator — the complete run lifecycle. operator_answer alone is unusable
    # (nothing to start, resume, inspect, or kill).
    "operator_start",
    "operator_answer",
    "operator_resume",
    "operator_status",
    "operator_kill",
    # Clone status
    "clone_status",
    # Practice playbook — the user's "which best practices to enforce, how hard"
    # control. Without it the enforcement gate can't be configured in-session.
    "sentigent_practices",
    # Routing self-correction — fold skill-router follow/ignore into routing_seeds.
    "sentigent_reconcile_routes",
})


def _tool():
    """Profile-aware replacement for @mcp.tool().

    In the "core" profile, functions not in CORE_TOOLS are defined but not
    registered with the MCP server, so they never reach the client's tool list.
    In "full" (default) every tool registers, exactly as before.
    """
    def decorate(fn):
        if _PROFILE == "core" and fn.__name__ not in CORE_TOOLS:
            return fn
        return mcp.tool()(fn)
    return decorate

# Thread-safe registry of Sentigent instances keyed by agent_id:profile
_judges: dict[str, Sentigent] = {}
_lock = threading.Lock()


def _get_judge(agent_id: str | None = None, profile: str | None = None) -> Sentigent:
    """Get or create a Sentigent instance from the registry."""
    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    prof = profile or os.environ.get("SENTIGENT_PROFILE", "code_review")
    key = f"{aid}:{prof}"

    with _lock:
        if key not in _judges:
            db_path = os.environ.get("SENTIGENT_DB_PATH", None)
            try:
                _judges[key] = Sentigent(profile=prof, agent_id=aid, db_path=db_path)
            except ValueError:
                _judges[key] = Sentigent(profile="default", agent_id=aid, db_path=db_path)
        return _judges[key]


@_tool()
def sentigent_evaluate(
    tool_name: str,
    tool_input: str,
    context: str = "{}",
    agent_state: str = "{}",
    agent_id: str = "",
    profile: str = "",
    task_id: str = "",
) -> str:
    """Evaluate an action before execution. Call this before risky operations.

    Returns a judgment decision: proceed, enrich, slow_down, or escalate.
    Now also includes:
    - Similar past episodes with lessons learned (context enrichment)
    - Policy violations detected
    - Actionable recommendations

    Args:
        tool_name: Name of the tool about to be called (e.g., "Bash", "Write", "Edit")
        tool_input: The input to the tool (command, file content, etc.)
        context: JSON string of additional context
        agent_state: JSON string of current agent state
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
        task_id: Optional task_id from sentigent_start_task(). Enables scope
                 enforcement and task-level learning. Recommended for all production use.
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

    ctx = json.loads(context) if isinstance(context, str) else context
    state = json.loads(agent_state) if isinstance(agent_state, str) else agent_state

    # Enrich context with tool-specific analysis
    ctx["tool_name"] = tool_name
    ctx["tool_input"] = tool_input  # expose for scope enforcement
    ctx = _enrich_context_from_tool(tool_name, tool_input, ctx)

    # ── Policy Check (BEFORE signal computation) ──
    policy_violations = check_policies(tool_name, tool_input, context=ctx)
    override_action = get_override_action(policy_violations)

    # ── Signal-based evaluation (with optional task context) ──
    decision = judge.evaluate(
        task=f"{tool_name}: {tool_input[:200]}",
        context=ctx,
        agent_state=state,
        task_id=task_id or None,
    )

    # ── Policy override: escalate/slow_down always wins ──
    final_action = decision.action.value
    final_reason = decision.reason

    if override_action:
        # Policy violations override the signal-based decision
        violation_msgs = [v.message for v in policy_violations]
        policy_reason = "; ".join(violation_msgs)

        if override_action == "escalate":
            final_action = "escalate"
            final_reason = f"POLICY VIOLATION: {policy_reason}"
        elif override_action == "slow_down" and final_action == "proceed":
            final_action = "slow_down"
            final_reason = f"Policy review required: {policy_reason}. Original: {final_reason}"
        elif override_action == "enrich" and final_action == "proceed":
            final_action = "enrich"
            final_reason = f"Policy requires more context: {policy_reason}. Original: {final_reason}"

    # ── Context Enrichment (similar past episodes) ──
    context_enrichment = _build_context_enrichment(judge, tool_name, tool_input, ctx)

    # Build response
    response: dict[str, Any] = {
        "trace_id": decision.trace_id,
        "action": final_action,
        "reason": final_reason,
        "signals": decision.signals,
        "judgment_score": decision.judgment_score,
        "confidence": decision.confidence,
    }
    if task_id:
        response["task_id"] = task_id

    # Add context enrichment if available
    if context_enrichment:
        response["context"] = context_enrichment

    # Add policy violations if any
    if policy_violations:
        response["policy_violations"] = [v.to_dict() for v in policy_violations]

    return json.dumps(response, indent=2)


@_tool()
def sentigent_record(
    tool_name: str,
    tool_input: str,
    tool_output: str = "",
    success: bool = True,
    duration_ms: int = 0,
    trace_id: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Record a trace after a tool execution. Called automatically by PostToolUse hooks.

    Args:
        tool_name: Name of the tool that was called
        tool_input: The input that was provided
        tool_output: The output/result (truncated if large)
        success: Whether the tool execution succeeded
        duration_ms: Execution duration in milliseconds
        trace_id: Optional trace_id from a previous evaluate() call
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

    # If we have a trace_id from evaluate, record the outcome for failures only.
    # Do NOT call evaluate() again — that would create a duplicate episode.
    if trace_id and not success:
        judge.record_outcome(
            trace_id, "incorrect", f"Tool {tool_name} failed: {tool_output[:200]}"
        )
    # If success, don't auto-attribute yet — wait for explicit feedback or
    # downstream signals (build pass, test pass, etc.)

    return json.dumps({
        "recorded": True,
        "trace_id": trace_id or "",
        "success": success,
    })


@_tool()
def sentigent_outcome(
    trace_id: str,
    outcome: str,
    feedback: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Record the outcome of a previous decision. This is how the agent learns.

    Call this when you know whether a decision was correct or not:
    - After tests pass/fail
    - After builds succeed/fail
    - After deploys succeed/fail
    - After developer provides feedback

    Args:
        trace_id: The trace_id from evaluate() or record()
        outcome: "correct", "incorrect", or "neutral"
        feedback: Optional explanation
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    judge.record_outcome(trace_id, outcome, feedback)

    return json.dumps({
        "recorded": True,
        "judgment_score": judge.judgment_score,
    })


@_tool()
def sentigent_feedback(
    trace_id: str,
    was_helpful: bool,
    comment: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Record developer feedback on a Sentigent suggestion.

    This is the interactive feedback loop — every response trains the judgment.

    Args:
        trace_id: The trace_id of the suggestion
        was_helpful: Whether the developer found the suggestion helpful
        comment: Optional comment
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    outcome = "correct" if was_helpful else "incorrect"
    judge.record_outcome(trace_id, outcome, comment or f"Developer feedback: helpful={was_helpful}")

    return json.dumps({
        "recorded": True,
        "judgment_score": judge.judgment_score,
        "message": "Thank you! Your feedback helps Sentigent learn." if was_helpful
                   else "Got it. Sentigent will adjust its thresholds.",
    })


def _resolve_score_window(window_days: int) -> int:
    """Resolve the recent-window size (in days) for the graded-only block.

    Precedence: an explicit positive ``window_days`` wins; otherwise fall back
    to the ``SENTIGENT_SCORE_WINDOW_DAYS`` env var when it is a valid int; else
    default to 7. Pure helper — no I/O beyond reading the environment.

    Args:
        window_days: Caller-supplied window; used as-is when > 0.

    Returns:
        The resolved positive window size in days.
    """
    if window_days > 0:
        return window_days
    env_val = os.environ.get("SENTIGENT_SCORE_WINDOW_DAYS")
    if env_val:
        try:
            parsed = int(env_val)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return 7


@_tool()
def sentigent_score(
    agent_id: str = "",
    profile: str = "",
    recent_window_days: int = 0,
) -> str:
    """Get the current judgment score and statistics.

    Returns the judgment score, total decisions, outcome breakdown,
    and learned baselines. Also surfaces a recent-window, graded-only
    accuracy block so real signal is visible past the legacy episode
    backlog (lifetime score dilutes recent behavior across ~78k episodes).

    Args:
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
        recent_window_days: Size of the recent window in days for the
            graded-only accuracy block (defaults to 7 when <= 0). Read-only.
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    stats = judge._memory.get_outcome_stats()
    baselines = judge._memory.get_baselines()
    episode_count = judge._memory.get_episode_count()

    baseline_summary = {}
    for name, b in baselines.items():
        baseline_summary[name] = {
            "median": round(b.median, 2),
            "std": round(b.std, 2),
            "sample_size": b.sample_size,
            "source": b.source,
        }

    window = _resolve_score_window(recent_window_days)
    recent_graded = judge._memory.get_recent_graded_accuracy(window)
    graded_total, graded_correct = judge._memory.get_outcome_counts(graded_only=True)

    return json.dumps({
        # Honest split: graded_* = human-graded outcomes only (the headline);
        # observed/judgment_score = legacy semantics, dominated by legacy
        # auto-recorded tool-status rows ("Bash command succeeded").
        "graded_score": judge.graded_judgment_score,
        "graded_total": graded_total,
        "graded_correct": graded_correct,
        "observed_score": judge.judgment_score,
        "judgment_score": judge.judgment_score,  # deprecated alias of observed_score
        "total_observations": episode_count,
        "total_episodes": episode_count,  # deprecated alias of total_observations
        "outcomes": stats,
        "learned_baselines": baseline_summary,
        "recent_graded": recent_graded,
    }, indent=2)


@_tool()
def sentigent_patterns(
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Get learned patterns from operational experience.

    Returns patterns the agent has learned, including:
    - What operations succeed/fail most often
    - What conditions predict good/bad outcomes
    - Recommendations based on accumulated experience

    Args:
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    episodes = judge._memory.find_similar_episodes("", limit=100)

    # Basic pattern analysis
    patterns = []

    # Analyze decision-outcome correlations
    escalations = [e for e in episodes if e.get("decision") == "escalate"]
    correct_escalations = [e for e in escalations if e.get("outcome") == "correct"]
    if escalations:
        patterns.append({
            "pattern": "escalation_accuracy",
            "description": (
                f"Escalations were correct {len(correct_escalations)}/{len(escalations)} times "
                f"({len(correct_escalations)/len(escalations)*100:.0f}%)"
            ),
            "sample_size": len(escalations),
        })

    proceeds = [e for e in episodes if e.get("decision") == "proceed"]
    correct_proceeds = [e for e in proceeds if e.get("outcome") == "correct"]
    if proceeds:
        patterns.append({
            "pattern": "proceed_accuracy",
            "description": (
                f"Proceed decisions were correct {len(correct_proceeds)}/{len(proceeds)} times "
                f"({len(correct_proceeds)/len(proceeds)*100:.0f}%)"
            ),
            "sample_size": len(proceeds),
        })

    return json.dumps({
        "patterns": patterns,
        "total_episodes_analyzed": len(episodes),
    }, indent=2)


@_tool()
def sentigent_insights(
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Get structured insights: correlations, trends, anomalies, and Brier Score.

    Returns engine-generated findings — not Claude Code interpretation.
    Call this instead of sentigent_score when you need actionable analysis.

    Args:
        agent_id: Optional agent identifier
        profile: Optional profile name
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    episodes = judge._memory.get_episodes_for_insights(limit=2000)

    correlations = []
    trends = []
    anomalies = []
    brier = 0.25
    recommendations: list[str] = []

    if len(episodes) >= 5:
        engine = judge._insights
        corr_insights = engine.compute_correlations(episodes)
        trend_insights = engine.detect_trends(episodes)
        anom_insights = engine.detect_anomalies(episodes)
        brier = engine._brier_score(episodes)

        correlations = [
            {"subject": i.subject, "finding": i.finding,
             "confidence": i.confidence, "signal_weight": i.signal_weight}
            for i in corr_insights
        ]
        trends = [
            {"subject": i.subject, "finding": i.finding, "confidence": i.confidence}
            for i in trend_insights
        ]
        anomalies = [
            {"subject": i.subject, "finding": i.finding, "confidence": i.confidence}
            for i in anom_insights
        ]
        seen: set[str] = set()
        for i in corr_insights + trend_insights + anom_insights:
            if i.recommendation and i.recommendation not in seen:
                recommendations.append(i.recommendation)
                seen.add(i.recommendation)

    return json.dumps({
        "correlations": correlations,
        "trends": trends,
        "anomalies": anomalies,
        "brier_score": round(brier, 4),
        "brier_interpretation": (
            "well-calibrated" if brier < 0.15
            else "moderate" if brier < 0.25
            else "poor — scores don't predict outcomes well"
        ),
        "recommendations": recommendations,
        "total_episodes_analyzed": len(episodes),
    }, indent=2)


@_tool()
def sentigent_trends(
    window_days: int = 7,
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Get time-series trend data for the dashboard and sentigent-learn skill.

    Returns per-day correct rates and episode counts for each tool.

    Args:
        window_days: How many days to include (default 7)
        agent_id: Optional agent identifier
        profile: Optional profile name
    """
    from datetime import datetime, timezone, timedelta
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    episodes = judge._memory.get_episodes_for_insights(limit=2000)

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=window_days)).isoformat()
    recent = [e for e in episodes if e["timestamp"] >= cutoff]

    by_date_tool: dict[str, dict[str, list]] = {}
    for ep in recent:
        date = ep["timestamp"][:10]
        tool = ep.get("tool_name") or "unknown"
        by_date_tool.setdefault(date, {}).setdefault(tool, []).append(ep)

    rows = []
    for date in sorted(by_date_tool):
        for tool, eps in by_date_tool[date].items():
            scored = [e for e in eps if e["outcome"] in ("correct", "incorrect")]
            correct_rate = (
                sum(1 for e in scored if e["outcome"] == "correct") / len(scored)
                if scored else None
            )
            rows.append({
                "date": date,
                "tool": tool,
                "correct_rate": round(correct_rate, 3) if correct_rate is not None else None,
                "episode_count": len(eps),
            })

    trend_insights = judge._insights.detect_trends(episodes, window_days=window_days)

    return json.dumps({
        "window_days": window_days,
        "daily_breakdown": rows,
        "trend_findings": [
            {"finding": i.finding, "confidence": i.confidence,
             "recommendation": i.recommendation}
            for i in trend_insights
        ],
    }, indent=2)


@_tool()
def sentigent_review(
    last_n: int = 50,
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Get a session review: good decisions, concerns, calibration score.

    The engine classifies decisions — no Claude Code interpretation needed.

    Good:    escalated when outcome was incorrect (escalation was warranted)
             OR proceeded when outcome was correct
    Concern: proceeded when outcome was incorrect (missed a problem)
             OR escalated when outcome was correct (unnecessary block)

    Args:
        last_n: Number of recent episodes to review (default 50)
        agent_id: Optional agent identifier
        profile: Optional profile name
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    review = judge._insights.compute_session_review(last_n=last_n)

    return json.dumps({
        "good_decisions": review.good_decisions,
        "concerns": review.concerns,
        "session_score": review.session_score,
        "session_score_pct": f"{review.session_score:.0%}",
        "brier_score": review.brier_score,
        "brier_interpretation": (
            "well-calibrated" if review.brier_score < 0.15
            else "moderate" if review.brier_score < 0.25
            else "poorly calibrated"
        ),
        "top_insight": review.top_insight,
        "total_reviewed": review.total_reviewed,
    }, indent=2)


def _build_context_enrichment(
    judge: Sentigent,
    tool_name: str,
    tool_input: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build context enrichment from similar past episodes.

    Returns a dict with:
    - similar_episodes: up to 3 relevant past episodes with outcomes/lessons
    - recommendation: actionable advice based on past patterns
    """
    task = f"{tool_name}: {tool_input[:200]}"

    try:
        similar = judge._memory.find_similar_episodes(task, context=context, limit=5)
    except Exception:
        return {}

    if not similar:
        return {}

    # Format the top 3 episodes into actionable context
    formatted_episodes = []
    correct_count = 0
    incorrect_count = 0

    for ep in similar[:3]:
        entry: dict[str, Any] = {
            "task": ep.get("task", "")[:100],
            "outcome": ep.get("outcome", "unknown"),
        }

        # Build a lesson from the outcome + feedback
        outcome = ep.get("outcome", "")
        feedback = ep.get("feedback", "")
        decision = ep.get("decision", "")

        if outcome == "correct":
            correct_count += 1
            if decision in ("escalate", "slow_down"):
                entry["lesson"] = feedback or f"Intervention ({decision}) was the right call"
            else:
                entry["lesson"] = feedback or "Proceeded successfully"
        elif outcome == "incorrect":
            incorrect_count += 1
            entry["lesson"] = feedback or f"This action failed — consider extra validation"
        else:
            entry["lesson"] = feedback or "No clear outcome recorded"

        formatted_episodes.append(entry)

    enrichment: dict[str, Any] = {
        "similar_episodes": formatted_episodes,
    }

    # Generate a recommendation based on patterns
    total = correct_count + incorrect_count
    if total > 0:
        failure_rate = incorrect_count / total
        if failure_rate >= 0.5:
            enrichment["recommendation"] = (
                f"Caution: similar actions failed {incorrect_count}/{total} times "
                f"({failure_rate:.0%}). Consider extra validation or testing before proceeding."
            )
        elif failure_rate > 0:
            enrichment["recommendation"] = (
                f"Note: similar actions had a {failure_rate:.0%} failure rate "
                f"({incorrect_count}/{total}). Review any differences from past successes."
            )
        else:
            enrichment["recommendation"] = (
                f"Good news: similar actions succeeded {correct_count}/{total} times. "
                f"Pattern looks safe."
            )

    return enrichment


@_tool()
def sentigent_context(
    task_description: str,
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Get contextual intelligence before taking an action.

    Call this anytime you want relevant context from past experience —
    not just before risky operations. Returns similar past episodes,
    learned patterns, and recommendations.

    This is the lightweight context engineering tool. Unlike sentigent_evaluate,
    it doesn't create a decision trace or produce signals. It just gives you
    intelligence to make better decisions.

    Args:
        task_description: What you're about to do (e.g., "Edit database.py, 80 lines")
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var)
    """
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

    try:
        similar = judge._memory.find_similar_episodes(
            task_description, limit=5,
        )
    except Exception:
        similar = []

    # Format episodes
    formatted_episodes = []
    outcomes: dict[str, int] = {"correct": 0, "incorrect": 0, "neutral": 0}

    for ep in similar[:5]:
        outcome = ep.get("outcome", "unknown")
        if outcome in outcomes:
            outcomes[outcome] += 1

        formatted_episodes.append({
            "task": ep.get("task", "")[:120],
            "decision": ep.get("decision", "unknown"),
            "outcome": outcome,
            "lesson": ep.get("feedback") or _infer_lesson(ep),
            "confidence": ep.get("confidence", 0),
        })

    # Get relevant baselines
    baselines = judge._memory.get_baselines()
    relevant_baselines: dict[str, Any] = {}
    for name, b in baselines.items():
        relevant_baselines[name] = {
            "median": round(b.median, 2),
            "std": round(b.std, 2),
            "range": f"[{round(b.p5, 2)}, {round(b.p95, 2)}]",
            "sample_size": b.sample_size,
        }

    # Get matching procedural rules
    rules = judge._memory.get_matching_rules({})
    relevant_rules = [
        {
            "pattern": r["pattern_name"],
            "action": r["learned_action"],
            "success_rate": round(r["success_rate"], 2),
            "samples": r["sample_size"],
        }
        for r in rules[:5]
    ]

    # Build recommendation
    total_with_outcomes = outcomes["correct"] + outcomes["incorrect"]
    recommendation = ""
    if total_with_outcomes > 0:
        failure_rate = outcomes["incorrect"] / total_with_outcomes
        if failure_rate >= 0.5:
            recommendation = (
                f"Warning: {failure_rate:.0%} failure rate on similar tasks. "
                "Consider adding tests, checking docs, or breaking into smaller steps."
            )
        elif failure_rate > 0:
            recommendation = (
                f"Some risk: {outcomes['incorrect']} of {total_with_outcomes} similar tasks "
                f"failed. Check differences from past successes."
            )
        else:
            recommendation = (
                f"Pattern looks good: {outcomes['correct']} similar tasks all succeeded. "
                f"Proceeding should be safe."
            )
    elif formatted_episodes:
        recommendation = "Past episodes found but no outcomes recorded yet. Consider extra caution."

    response: dict[str, Any] = {
        "similar_episodes": formatted_episodes,
        "recommendation": recommendation,
        "judgment_score": judge.judgment_score,
    }

    if relevant_baselines:
        response["baselines"] = relevant_baselines
    if relevant_rules:
        response["learned_rules"] = relevant_rules

    return json.dumps(response, indent=2)


def _infer_lesson(episode: dict[str, Any]) -> str:
    """Infer a lesson from an episode when no explicit feedback exists."""
    outcome = episode.get("outcome", "")
    decision = episode.get("decision", "")

    if outcome == "correct" and decision == "proceed":
        return "Action succeeded as expected"
    elif outcome == "correct" and decision in ("escalate", "slow_down"):
        return f"{decision.replace('_', ' ').title()} was the right call"
    elif outcome == "incorrect" and decision == "proceed":
        return "Should have been more cautious — action led to a problem"
    elif outcome == "incorrect" and decision in ("escalate", "slow_down"):
        return "Intervention was unnecessary — consider adjusting thresholds"
    return "No clear lesson"


def _enrich_context_from_tool(
    tool_name: str,
    tool_input: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Add tool-specific context for better signal computation."""

    if tool_name == "Bash":
        # Detect dangerous commands
        dangerous_commands = ["rm -rf", "rm -r", "DROP TABLE", "TRUNCATE", "reset --hard",
                            "push --force", "push -f", "--no-verify", "format", "mkfs"]
        for cmd in dangerous_commands:
            if cmd.lower() in tool_input.lower():
                context["is_destructive"] = True
                context["destructive_command"] = cmd
                context["consequence_severity"] = 0.9
                break

        # Detect deployment-related commands
        deploy_keywords = ["deploy", "push", "publish", "release"]
        for kw in deploy_keywords:
            if kw in tool_input.lower():
                context["is_deployment"] = True
                break

    elif tool_name in ("Write", "Edit"):
        # Detect sensitive file changes
        sensitive_patterns = [".env", "secret", "credential", "password", "token", "key"]
        for pattern in sensitive_patterns:
            if pattern in tool_input.lower():
                context["is_sensitive_file"] = True
                context["consequence_severity"] = 0.8
                break

        # Estimate change size
        context["lines_changed"] = tool_input.count("\n")

    return context



@_tool()
def sentigent_layer2(
    agent_id: str = "",
    profile: str = "",
    sync_now: bool = False,
) -> str:
    """Get Layer 2 (Supabase) sync status, org-wide scores, and learned patterns.

    Shows how your local learning compares to the org-wide picture in Supabase.
    Optionally triggers an immediate sync.

    Args:
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID)
        profile: Optional profile name (defaults to SENTIGENT_PROFILE)
        sync_now: If true, push latest episodes and patterns to Supabase immediately
    """
    import os as _os

    supabase_url = _os.environ.get("SUPABASE_URL", "")
    has_key = bool(
        _os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or _os.environ.get("SUPABASE_ANON_KEY")
    )

    if not supabase_url or not has_key:
        return json.dumps({
            "status": "not_configured",
            "message": "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to enable Layer 2 sync.",
        }, indent=2)

    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

    try:
        from sentigent.sync.manager import SyncManager
        sync = SyncManager(org_id=judge._org_id, agent_id=judge._agent_id)

        result: dict[str, Any] = {"status": "active", "supabase_url": supabase_url}

        # Org-wide judgment score
        org_score = sync.get_judgment_score()
        result["org_judgment_score"] = org_score

        # Local vs org comparison
        local_stats = judge._memory.get_outcome_stats()
        local_total = sum(local_stats.values())
        result["local_episodes"] = local_total
        result["local_outcomes"] = local_stats
        result["local_judgment_score"] = round(judge.judgment_score, 4)

        # Pull org patterns
        org_patterns = sync.pull_org_patterns(judge._profile.name)
        result["org_patterns"] = [
            {
                "name": p["pattern_name"],
                "action": p["learned_action"],
                "success_rate": f"{p['success_rate']:.1%}",
                "sample_size": p["sample_size"],
            }
            for p in org_patterns
        ]

        # Optional immediate sync
        if sync_now:
            episodes = judge._memory.get_episodes_with_outcomes(
                agent_id=judge._agent_id, limit=500,
            )
            sync_result = sync.push_episodes(episodes)
            result["sync_result"] = sync_result

        return json.dumps(result, indent=2)

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)

@_tool()
def sentigent_coach(
    agent_id: str = "",
    lookback_days: int = 7,
    format: str = "text",
) -> str:
    """AI-powered interaction coach that analyzes your agent patterns and suggests improvements.

    Observes how you and your agent have been working together, identifies what's
    working and what's struggling, then uses Claude Haiku to generate specific,
    actionable suggestions for improving your prompts and workflows.

    Args:
        agent_id: Agent to analyze (default: from env or 'hussain')
        lookback_days: How many days of history to analyze (default: 7)
        format: 'text' for readable report, 'json' for structured data

    Returns:
        Coaching report with tool performance, workflow patterns, and AI suggestions.
    """
    from sentigent.core.coach import InteractionCoach

    resolved_agent_id = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "hussain")

    try:
        coach = InteractionCoach(agent_id=resolved_agent_id)
        report = coach.analyze(lookback_days=lookback_days)

        if format == "json":
            return json.dumps(report.to_dict(), indent=2)
        return report.to_text()

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_bash_failures() -> str:
    """Query recent Bash tool failures detected by Sentigent hooks.

    Returns a summary of which commands have been failing, how many times,
    and what MCP alternatives Sentigent has suggested.

    Use this to understand why Claude Code is struggling with certain Bash
    operations and what tools to prefer instead.
    """
    from pathlib import Path

    fail_file = Path("/tmp/sentigent_bash_failures.json")
    if not fail_file.exists():
        return json.dumps({
            "status": "no_failures_recorded",
            "message": "No Bash failures have been detected since last hook restart.",
        }, indent=2)

    try:
        failures = json.loads(fail_file.read_text())
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)

    if not failures:
        return json.dumps({"status": "no_failures", "count": 0}, indent=2)

    # Group by command prefix for summary
    from collections import defaultdict
    import time

    by_cmd: dict[str, list] = defaultdict(list)
    for f in failures:
        cmd = f.get("command", "")
        prefix = cmd.split()[0] if cmd.split() else "unknown"
        by_cmd[prefix].append(f)

    summary = []
    for cmd_prefix, entries in sorted(by_cmd.items(), key=lambda x: -len(x[1])):
        last = entries[-1]
        age_mins = (time.time() - last.get("ts", 0)) / 60
        summary.append({
            "command": cmd_prefix,
            "failure_count": len(entries),
            "last_error": last.get("error", "")[:100],
            "suggested_tool": last.get("suggested_tool", "mcp__desktop-commander"),
            "last_seen_mins_ago": round(age_mins, 1),
        })

    return json.dumps({
        "status": "failures_detected",
        "total_failures": len(failures),
        "unique_commands": len(by_cmd),
        "by_command": summary,
        "advice": "Use the suggested_tool for each failing command instead of Bash.",
    }, indent=2)


@_tool()
def sentigent_prove(
    agent_id: str = "",
    days: int = 90,
) -> str:
    """Proof-of-value report: evidence that Sentigent is working.

    Shows confirmed catches (interventions that were correct), false negatives
    (actions cleared that later failed), intervention accuracy, score trajectory,
    org policy enforcement stats, and per-agent compliance across the org.

    Use this to answer: "Is Sentigent actually helping us?"

    Args:
        agent_id: Agent to analyze (default: from env)
        days: Look-back window in days (default: 90)

    Returns:
        JSON report with proof metrics + top catches narrative.
    """
    from sentigent.core.prove import ProofEngine

    resolved_agent_id = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "hussain")
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    try:
        engine = ProofEngine(agent_id=resolved_agent_id, org_id=resolved_org_id)
        report = engine.compute(days=days)
        return json.dumps(report.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_hub_status() -> str:
    """
    Get the intelligence hub status: connected agents, learning activity,
    collective judgment score, and latest insights.

    The hub is the central intelligence layer connecting all agents in your org.
    More agents connected = better collective intelligence for all.
    """
    try:
        from sentigent.intelligence.hub import get_hub
        import os
        org_id = os.environ.get("SENTIGENT_ORG_ID", "")
        hub = get_hub(org_id=org_id)
        status = hub.status()
        network = hub.get_agent_network()
        return json.dumps({
            "status": "ok",
            "hub": {
                "running": status.running,
                "org_id": status.org_id,
                "connected_agents": status.connected_agents,
                "total_signals_processed": status.total_signals_processed,
            },
            "agents": network,
            "learner": status.learner_report,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_peer_patterns(limit: int = 10) -> str:
    """
    Get high-confidence patterns learned by peer agents in your org.

    These are patterns where other agents have taken an action with >80%
    success rate across many decisions. Applying peer patterns to your
    own decisions increases collective intelligence.

    Args:
        limit: Max patterns to return (default 10)
    """
    try:
        from sentigent.intelligence.hub import get_hub
        import os
        org_id = os.environ.get("SENTIGENT_ORG_ID", "")
        hub = get_hub(org_id=org_id)
        patterns = hub.get_peer_patterns(limit=limit)
        return json.dumps({
            "status": "ok",
            "patterns": patterns,
            "count": len(patterns),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_learn_now() -> str:
    """
    Trigger an immediate collective learning cycle.

    The learner normally runs every 30 seconds in the background. Use this
    to force an immediate cycle — useful after a burst of new outcomes or
    when you want the latest threshold updates applied now.

    Returns: threshold updates, new auto-generated policies, and cross-agent insights.
    """
    try:
        from sentigent.intelligence.hub import get_hub
        import os
        org_id = os.environ.get("SENTIGENT_ORG_ID", "")
        hub = get_hub(org_id=org_id)
        if not hub._learner:
            return json.dumps({"status": "error", "error": "Learner not initialized"})
        report = hub._learner.run_once()
        return json.dumps({
            "status": "ok",
            "agents_analyzed": report.agents_analyzed,
            "threshold_updates": [
                {
                    "signal": u.signal,
                    "old": u.old_value,
                    "new": u.new_value,
                    "samples": u.supporting_samples,
                    "gain": u.estimated_accuracy_gain,
                }
                for u in report.threshold_updates
            ],
            "policies_generated": report.policies_generated,
            "insights": report.cross_agent_insights,
            "regression_detected": report.regression_detected,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_agent_bus() -> str:
    """
    Show the inter-agent message bus — registered agents, capabilities, and recent messages.

    The AgentBus enables direct agent-to-agent messaging and capability-based task
    routing within the org. Use this to see which agents are registered and what
    they can handle.

    Returns: registered agents with capabilities, and the last 20 bus messages.
    """
    try:
        from sentigent.intelligence.agent_bus import get_agent_bus
        import os
        bus = get_agent_bus(org_id=os.environ.get("SENTIGENT_ORG_ID", ""))
        return json.dumps({
            "status": "ok",
            "agents": bus.list_agents(),
            "recent_messages": bus.recent_messages(limit=20),
        }, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_executor_stats() -> str:
    """
    Show ActionExecutor statistics — how often each action type was executed and latency.

    The executor runs concrete side-effects after every evaluate() call:
    - escalate: fires escalation event + webhooks
    - slow_down: introduces a delay
    - enrich: fetches peer patterns from hub
    - proceed: no-op

    Returns: per-action stats (count, avg latency ms).
    """
    try:
        from sentigent.intelligence.executor import get_executor
        executor = get_executor()
        stats = executor.get_stats()
        result = {}
        for action, s in stats.items():
            count = s.get("count", 0)
            total_ms = s.get("total_ms", 0.0)
            result[action] = {
                "count": int(count),
                "avg_latency_ms": round(total_ms / count, 2) if count else 0.0,
                "total_ms": round(total_ms, 1),
            }
        return json.dumps({"status": "ok", "stats": result}, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_reconcile_routes(
    days: int = 0,
    dry_run: bool = False,
    agent_id: str = "",
) -> str:
    """Fold skill-router follow/ignore signal into routing_seeds.outcome.

    Correlates skill-router's embedding-route decisions (which skill it chose per
    prompt) against skill_usage.log invocations (which skill you actually ran),
    then writes the verdict back so the embedding router self-corrects: routes you
    consistently ignore stop firing, routes you follow are reinforced.

    Args:
        days: only consider events from the last N days (0 = all history).
        dry_run: report what WOULD change without writing.
        agent_id: optional agent identifier.
    """
    import time as _time
    from sentigent.routing import reconciler

    judge = _get_judge(agent_id=agent_id or None)
    since = (_time.time() - days * 86400) if days > 0 else 0.0
    routes = reconciler.parse_route_events(reconciler.ROUTER_LOG_DEFAULT, since=since)
    invs = reconciler.parse_invocations(reconciler.USAGE_LOG_DEFAULT, since=since)

    if dry_run:
        return json.dumps({
            "dry_run": True, "parsed_routes": len(routes),
            "invocations": len(invs), **reconciler.preview(routes, invs),
        }, indent=2)

    stats = reconciler.reconcile_outcomes(judge._memory, routes, invs)
    return json.dumps({
        "parsed_routes": len(routes), "invocations": len(invs), **stats,
    }, indent=2)


@_tool()
def sentigent_practices(
    action: str = "list",
    text: str = "",
    domain: str = "global",
    cadence: str = "commit",
    practice_id: int = 0,
    enforcement: str = "",
    active: str = "",
    agent_id: str = "",
) -> str:
    """Manage your best-practice playbook — which practices get enforced, how hard.

    This is the user-facing control for the practice enforcement gate: declare a
    practice once and Sentigent holds you (and the loop driver) to it, so you
    stop re-prompting "did you run the tests?" / "did you review the diff?".

    Actions:
      - "list"         → show your practices with adherence + enforcement level.
      - "add"          → add a practice (text, domain, cadence). New practices
                         start at enforcement='warn'.
      - "enforce"      → set practice_id's enforcement to 'off' | 'warn' | 'block'.
                         off = ignore, warn = slow_down the action with a note,
                         block = escalate (hard-gate) until the practice is met.
      - "toggle"       → set active='true'|'false' for practice_id.

    Cadence is when it fires: 'commit' (git commit), 'pr' (git push / open PR),
    'deploy', 'milestone', or 'always'. Only positive "do-X-before-Y" practices
    are gate-enforced; prohibitions like "never force-push" stay in policies.
    """
    judge = _get_judge(agent_id=agent_id or None)
    store = judge._memory
    act = (action or "list").strip().lower()

    try:
        if act == "add":
            if not text.strip():
                return json.dumps({"error": "add requires 'text'"})
            pid = store.add_practice(text.strip(), domain=domain, cadence=cadence)
            return json.dumps({"added": pid, "text": text.strip(),
                               "cadence": cadence, "enforcement": "warn"}, indent=2)
        if act == "enforce":
            if not practice_id:
                return json.dumps({"error": "enforce requires 'practice_id'"})
            store.set_practice_enforcement(practice_id, enforcement)
            return json.dumps({"practice_id": practice_id,
                               "enforcement": enforcement.strip().lower()}, indent=2)
        if act == "toggle":
            if not practice_id:
                return json.dumps({"error": "toggle requires 'practice_id'"})
            store.set_practice_active(practice_id, active.strip().lower() in ("1", "true", "yes", "on"))
            return json.dumps({"practice_id": practice_id, "active": active}, indent=2)

        rows = store.get_practices(active_only=False)
        return json.dumps({
            "practices": [
                {
                    "id": r["id"], "text": r["text"], "domain": r["domain"],
                    "cadence": r["cadence"], "active": bool(r["active"]),
                    "enforcement": r.get("enforcement", "warn"),
                    "followed": r["times_followed"], "skipped": r["times_skipped"],
                }
                for r in rows
            ],
            "hint": "enforce id block  →  hard-gate that practice; off  →  ignore it",
        }, indent=2)
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as exc:
        return json.dumps({"error": f"practices op failed: {exc}"})


@_tool()
def sentigent_policy(
    action: str = "list",
    policy_name: str = "",
    trigger_tool: str = "*",
    trigger_pattern: str = "",
    enforce_action: str = "slow_down",
    enforce_reason: str = "",
    severity: str = "medium",
) -> str:
    """Manage org-wide enforcement policies (Layer 2).

    Org policies are enforced across ALL agents in the org simultaneously.
    A policy fires BEFORE individual agent judgment — it's the highest-priority override.

    Actions:
      list    → Show all active policies for this org
      add     → Add a new policy rule
      disable → Disable an existing policy by name

    Enforcement actions:
      block    → Hard block the tool call (agent cannot proceed)
      escalate → Block + require human confirmation
      slow_down → Approve but warn the agent
      enrich   → Approve but ask agent to gather more context first

    Example — block force pushes org-wide:
      sentigent_policy(action="add", policy_name="no_force_push",
                       trigger_tool="Bash", trigger_pattern="push --force",
                       enforce_action="block", severity="critical",
                       enforce_reason="Force pushing overwrites others work.")

    Args:
        action: 'list', 'add', or 'disable'
        policy_name: Policy name (required for add/disable)
        trigger_tool: Tool to match: 'Bash', 'Write', 'Edit', or '*' (any)
        trigger_pattern: Regex pattern matched against the tool input
        enforce_action: What to do when policy fires
        enforce_reason: Human-readable explanation shown to agent
        severity: 'low', 'medium', 'high', or 'critical'

    Returns:
        JSON with policy list or operation result.
    """
    org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        return json.dumps({"error": "Layer 2 not configured. Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY."})

    try:
        from supabase import create_client
        client = create_client(url, key)
    except Exception as exc:
        return json.dumps({"error": f"Supabase connection failed: {exc}"})

    if action == "list":
        try:
            result = (
                client.table("org_policies")
                .select("policy_name,trigger_tool,trigger_pattern,enforce_action,enforce_reason,severity,is_active,trigger_count,last_triggered")
                .eq("org_id", org_id)
                .execute()
            )
            return json.dumps({"org_id": org_id, "policies": result.data or []}, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    elif action == "add":
        if not policy_name:
            return json.dumps({"error": "policy_name is required for add"})
        try:
            client.table("org_policies").insert({
                "org_id": org_id,
                "policy_name": policy_name,
                "trigger_tool": trigger_tool,
                "trigger_pattern": trigger_pattern,
                "enforce_action": enforce_action,
                "enforce_reason": enforce_reason,
                "severity": severity,
                "is_active": True,
                "created_by": os.environ.get("SENTIGENT_AGENT_ID", "mcp"),
            }).execute()
            return json.dumps({
                "status": "ok",
                "message": f"Policy '{policy_name}' added",
                "enforce_action": enforce_action,
                "trigger": f"{trigger_tool}:{trigger_pattern}",
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    elif action == "disable":
        if not policy_name:
            return json.dumps({"error": "policy_name is required for disable"})
        try:
            client.table("org_policies").update({"is_active": False}).eq(
                "org_id", org_id
            ).eq("policy_name", policy_name).execute()
            return json.dumps({"status": "ok", "message": f"Policy '{policy_name}' disabled"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return json.dumps({"error": f"Unknown action: {action}. Use list, add, or disable."})


@_tool()
def sentigent_metrics() -> str:
    """Return a snapshot of Sentigent's runtime observability metrics.

    Includes decision counters (by action type), outcome counters,
    evaluate() latency percentiles (p50/p95/p99), memory failure counts,
    pattern mine counts, and episode storage stats.

    Use this to diagnose performance issues or verify that Sentigent
    is operating within expected latency bounds.

    Returns:
        JSON with 'counters' (all named counters) and 'latency_stats'
        (p50, p95, p99, mean, min, max, count for evaluate_latency_ms).
    """
    from sentigent.observability import get_metrics

    try:
        metrics = get_metrics()
        snap = metrics.snapshot()
        return json.dumps({
            "status": "ok",
            "metrics": snap,
            "note": "Set metrics_enabled=true in pyproject.toml [tool.sentigent] to enable collection.",
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_profile(
    action: str = "get",
    profile_name: str = "",
    agent_id: str = "",
) -> str:
    """Manage org-level agent profiles (Layer 2 profile intelligence).

    Profiles shape how agents evaluate decisions by applying role-specific
    value weights and signal thresholds. Built-in roles: product_manager,
    security_engineer, data_analyst, devops_engineer.

    Actions:
        get        — Show the current effective profile for an agent
        list       — List all available profiles (builtin + org-defined)
        assign     — Assign a profile to an agent (persists to Supabase)
        builtin    — List all built-in profile templates with descriptions

    Args:
        action: "get" | "list" | "assign" | "builtin"
        profile_name: Profile name (required for 'assign')
        agent_id: Agent ID (uses default from env if not provided)

    Returns:
        JSON with profile details or confirmation.
    """
    from sentigent.core.profile_intelligence import (
        get_profile_intelligence,
        ProfileIntelligence,
    )

    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    judge = _get_judge(agent_id=aid)
    org_id = judge._org_id or "default"

    pi = get_profile_intelligence(org_id=org_id, agent_id=aid)

    try:
        if action == "get":
            report = pi.get_profile_report()
            return json.dumps({"status": "ok", "profile": report.to_dict()}, indent=2)

        elif action == "list":
            report = pi.get_profile_report()
            return json.dumps({
                "status": "ok",
                "active_profile": report.active_profile,
                "available_profiles": report.available_profiles,
            }, indent=2)

        elif action == "assign":
            if not profile_name:
                return json.dumps({"status": "error", "error": "profile_name required for assign"})
            saved = pi.assign_profile(profile_name)
            return json.dumps({
                "status": "ok",
                "assigned": profile_name,
                "agent_id": aid,
                "persisted_to_supabase": saved,
                "note": "Profile takes effect immediately. Supabase persist requires org_profiles table (migration 003).",
            }, indent=2)

        elif action == "builtin":
            profiles = ProfileIntelligence.list_builtin_profiles()
            return json.dumps({"status": "ok", "builtin_profiles": profiles}, indent=2)

        else:
            return json.dumps({"status": "error", "error": f"Unknown action: {action}. Use: get, list, assign, builtin"})

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_prompt_health(
    lookback_days: int = 30,
    agent_id: str = "",
    format: str = "json",
) -> str:
    """Analyze prompt quality patterns to help improve agent interactions.

    Observes which prompt styles lead to correct vs incorrect outcomes,
    detects problematic patterns (vague, ambiguous, passive voice), and
    generates specific rewrite suggestions.

    This helps the USER write better instructions for their AI agent —
    the key insight being that prompt quality directly drives outcome quality.

    Args:
        lookback_days: How many days of history to analyze (default 30)
        agent_id: Agent to analyze (uses default from env if not provided)
        format: "json" or "text" (text for terminal display)

    Returns:
        PromptHealthReport with health score, pattern analysis, and improvements.
    """
    from sentigent.core.prompt_observer import PromptObserver

    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")

    try:
        observer = PromptObserver(agent_id=aid)
        report = observer.analyze(lookback_days=lookback_days)

        if format == "text":
            return report.to_text()

        return json.dumps({"status": "ok", "report": report.to_dict()}, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_collective(
    action: str = "status",
    profile_name: str = "default",
    opt_in: bool = True,
    industry_tags: list[str] | None = None,
) -> str:
    """Manage Layer 3 collective intelligence — cross-org anonymized pattern sharing.

    Actions:
      status     — show opt-in status and pool stats
      opt_in     — opt this org into contributing patterns for a profile
      opt_out    — opt this org out of contributing patterns for a profile
      pull       — pull cross-org patterns from the shared pool
      contribute — manually trigger contributing recent patterns to the pool
    """
    try:
        from sentigent.sync.manager import SyncManager
        from sentigent.learning.pattern_miner import PatternMiner

        engine = _get_engine()
        mgr = SyncManager(org_id=engine._org_id, agent_id=engine._agent_id)

        if action == "status":
            status = mgr.get_layer3_status()
            lines = [
                "=== Layer 3 Collective Intelligence ===",
                f"Pool size:          {status.get('pool_size', 0)} patterns",
                f"Multi-org patterns: {status.get('multi_org_patterns', 0)}",
                f"Avg success rate:   {status.get('pool_avg_success_rate', 0):.1%}",
                f"Opted-in profiles:  {', '.join(status.get('opted_in_profiles', [])) or 'none'}",
            ]
            return "\n".join(lines)

        elif action in ("opt_in", "opt_out"):
            opted = action == "opt_in"
            ok = mgr.set_layer3_opt_in(profile_name, opted)
            if ok:
                return (
                    f"Layer 3: org {'opted IN to' if opted else 'opted OUT of'} "
                    f"contributing patterns for profile={profile_name}"
                )
            return "Layer 3: failed to update opt-in status"

        elif action == "pull":
            patterns = mgr.pull_layer3_patterns(industry_tags=industry_tags)
            if not patterns:
                return "Layer 3: no patterns in the shared pool yet"
            lines = [f"Layer 3 shared patterns ({len(patterns)} total):"]
            for p in patterns[:20]:
                lines.append(
                    f"  {p['pattern_name']:50s} → {p['learned_action']:12s}  "
                    f"rate={p['success_rate']:.0%}  orgs={p['contributing_org_count']}"
                )
            return "\n".join(lines)

        elif action == "contribute":
            miner = PatternMiner(db_path=engine._db_path)
            local_patterns = miner.get_patterns(min_success_rate=0.85, min_samples=5)
            if not local_patterns:
                return (
                    "Layer 3: no qualifying patterns to contribute "
                    "(need success_rate≥0.85 and 5+ samples)"
                )
            result = mgr.contribute_to_layer3(
                [
                    {
                        "pattern_name": p.pattern_name,
                        "learned_action": p.learned_action,
                        "success_rate": p.success_rate,
                        "sample_size": p.sample_size,
                    }
                    for p in local_patterns
                ],
                profile_name=profile_name,
                industry_tags=industry_tags,
            )
            if not result["opted_in"]:
                return (
                    f"Layer 3: not opted in for profile={profile_name}. "
                    f"Run: sentigent_collective(action='opt_in', profile_name='{profile_name}')"
                )
            return (
                f"Layer 3 contribution: {result['contributed']} patterns shared, "
                f"{result['skipped']} skipped (below threshold)"
            )

        return f"Unknown action: {action}. Use: status, opt_in, opt_out, pull, contribute"

    except Exception as exc:
        return f"Layer 3 error: {exc}"


@_tool()
def sentigent_prompt_build(
    action: str = "list",
    template: str = "",
    session_id: str = "",
    answer: str = "",
    profile: str = "default",
) -> str:
    """Interactively build a well-structured prompt using a guided template.

    Sentigent asks clarifying questions and assembles a copy-paste-ready prompt.

    Actions:
        list     → show all available templates (default)
        start    → begin a new session (requires: template)
        answer   → answer the current question (requires: session_id, answer)
        skip     → skip the current optional field (requires: session_id)
        status   → see current session state (requires: session_id)
        abandon  → cancel a session (requires: session_id)

    Templates: product_spec, pr_review, bug_report, code_refactor,
               architecture_decision, api_design, task_breakdown

    Examples:
        sentigent_prompt_build(action="list")
        sentigent_prompt_build(action="start", template="product_spec")
        sentigent_prompt_build(action="answer", session_id="abc123", answer="My SaaS login feature")
        sentigent_prompt_build(action="skip", session_id="abc123")
        sentigent_prompt_build(action="status", session_id="abc123")
    """
    import json as _json
    from sentigent.core.prompt_builder import (
        list_templates,
        start_session,
        answer_field,
        skip_field,
        get_session_status,
        abandon_session,
    )

    try:
        if action == "list":
            templates = list_templates()
            lines = ["Available prompt templates:\n",
                     f"  {'Template':<22}  {'Skill invoked':<28}  Description",
                     "  " + "─" * 80]
            for t in templates:
                lines.append(
                    f"  {t['name']:<22}  {t['skill']:<28}  {t['description']}"
                    f"  ({t['required_fields']} fields)"
                )
            lines.append(
                "\nStart: sentigent_prompt_build(action='start', template='<name>')"
            )
            lines.append(
                "When complete, the right Claude Code skill is invoked automatically."
            )
            return "\n".join(lines)

        elif action == "start":
            if not template:
                return "Error: 'template' is required for action='start'. Use action='list' to see options."
            result = start_session(template, profile=profile)
            if "error" in result:
                return f"Error: {result['error']}"
            return _format_question(result)

        elif action == "answer":
            if not session_id:
                return "Error: 'session_id' is required for action='answer'."
            result = answer_field(session_id, answer)
            if "error" in result and result.get("status") != "needs_answer":
                return f"Error: {result['error']}"
            if result.get("status") == "complete":
                return _format_complete(result)
            if result.get("status") == "needs_answer":
                return f"⚠ {result['error']}\n\n{_format_question(result)}"
            return _format_question(result)

        elif action == "skip":
            if not session_id:
                return "Error: 'session_id' is required for action='skip'."
            result = skip_field(session_id)
            if "error" in result:
                return f"Error: {result['error']}"
            if result.get("status") == "complete":
                return _format_complete(result)
            return _format_question(result)

        elif action == "status":
            if not session_id:
                return "Error: 'session_id' is required for action='status'."
            result = get_session_status(session_id)
            if "error" in result:
                return f"Error: {result['error']}"
            lines = [
                f"Session: {result['session_id']}  Template: {result['template']}  Progress: {result['progress']}",
                "",
                "Answers so far:",
            ]
            for k, v in result["answers_so_far"].items():
                lines.append(f"  {k}: {v[:60]}{'...' if len(v) > 60 else ''}")
            lines.append(f"\nCurrent question: {result['current_question']}")
            return "\n".join(lines)

        elif action == "abandon":
            if not session_id:
                return "Error: 'session_id' is required for action='abandon'."
            result = abandon_session(session_id)
            if "error" in result:
                return f"Error: {result['error']}"
            return f"Session {session_id} abandoned."

        else:
            return f"Unknown action '{action}'. Valid: list, start, answer, skip, status, abandon"

    except Exception as exc:
        return f"Prompt builder error: {exc}"


def _format_question(result: dict) -> str:
    """Format a question step for display."""
    lines = []
    progress = result.get("progress", "")
    template = result.get("template", "")
    if template:
        lines.append(f"[{template}] Building prompt — step {progress}")
        lines.append("")

    required_marker = "" if result.get("required", True) else " (optional — say 'skip' to skip)"
    lines.append(f"❓ {result['question']}{required_marker}")

    if result.get("hint"):
        lines.append(f"   💡 {result['hint']}")

    if result.get("placeholder"):
        lines.append(f"   Example: {result['placeholder']}")

    session_id = result.get("session_id", "")
    if session_id:
        lines.append(f"\n   session_id: {session_id}")

    remaining = result.get("fields_remaining")
    if remaining is not None:
        lines.append(f"   {remaining} question(s) remaining after this")

    return "\n".join(lines)


def _format_complete(result: dict) -> str:
    """Format the completed prompt and emit a skill invocation directive."""
    skill = result.get("skill_to_invoke", "feature-dev:feature-dev")
    prompt = result["prompt"]
    lines = [
        f"✅ Prompt complete! ({result['field_count']} fields filled)",
        "",
        "─" * 60,
        prompt,
        "─" * 60,
        "",
        f"🚀 NEXT ACTION: Invoke the `{skill}` skill now with the prompt above as args.",
        f'   Skill(skill="{skill}", args="""',
        prompt,
        '""")',
        "",
        "Execute this immediately — the skill will run the full assembled prompt.",
    ]
    return "\n".join(lines)


@_tool()
def sentigent_world_model(
    query: str = "",
    agent_id: str = "",
) -> str:
    """Query the org world model — vocabulary, security practices, domain entities, member contexts.

    The world model is what Layer 2 knows about your organization from observing all
    agent activity. It captures:
      - Org-specific lingo (what "deploy" means here, what "ship it" implies)
      - Security practices (what gets blocked/escalated and why)
      - Domain entities (which services and databases are critical)
      - Member contexts (per-person risk tolerance and communication style)

    Without the world model, judgment is generic. With it, judgment is org-specific.

    Args:
        query: Optional task/context to filter relevant world model entries.
               If empty, returns the full org world model summary.
        agent_id: Agent/member identifier for member context lookup.

    Returns:
        JSON with vocabulary, security practices, entities, member context.
    """
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    resolved_agent_id = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "")

    if not resolved_org_id:
        return json.dumps({
            "status": "unavailable",
            "reason": "SENTIGENT_ORG_ID not set — world model requires Layer 2 (Supabase)",
        }, indent=2)

    try:
        from sentigent.sync.manager import _get_supabase_client as _get_sb
        from sentigent.memory.world_model import WorldModelQuery

        client = _get_sb()
        wm = WorldModelQuery(client, resolved_org_id)

        if query:
            ctx = wm.get_context(task=query, agent_id=resolved_agent_id)
            return json.dumps({
                "status": "ok",
                "query": query,
                "context": ctx.to_dict(),
                "prompt_fragment": ctx.to_prompt_fragment(),
            }, indent=2)
        else:
            full = wm.get_full_world_model()
            return json.dumps({"status": "ok", **full}, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_start_task(
    goal: str,
    scope: str = "[]",
    authorized_by: str = "user",
    success_criteria: str = "[]",
    constraints: str = "[]",
    task_id: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Declare a task before acting. Returns a task_id to pass to evaluate().

    This is the foundational call for task-anchored judgment (Phase 2).
    Every action you take as part of this task should pass the returned
    task_id to sentigent_evaluate(). This enables:
      - Scope enforcement: actions outside declared scope auto-escalate
      - Constraint memory: stated constraints persist for the entire task
      - Task-level learning: outcomes are attributed at the task level

    Args:
        goal: What you are trying to accomplish (be specific)
        scope: JSON array of files/services you are authorized to touch.
               e.g. '["auth/middleware.py", "auth/validators.py"]'
               Leave empty for unrestricted scope.
        authorized_by: Who authorized this task ('user' | 'policy' | 'org_admin')
        success_criteria: JSON array of observable completion signals.
                          e.g. '["JWT validation passes all tests"]'
        constraints: JSON array of things you must NOT do.
                     e.g. '["do not touch OAuth flow", "no schema migrations"]'
        task_id: Optional custom task_id (leave empty for auto-generated UUID)
        agent_id: Optional agent identifier
        profile: Optional profile name

    Returns:
        JSON with task_id and confirmation. Pass task_id to all subsequent
        sentigent_evaluate() calls for this task.
    """
    import json as _json

    scope_list = _json.loads(scope) if scope and scope != "[]" else []
    success_list = _json.loads(success_criteria) if success_criteria and success_criteria != "[]" else []
    constraints_list = _json.loads(constraints) if constraints and constraints != "[]" else []

    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    tid = judge.start_task(
        goal=goal,
        scope=scope_list,
        authorized_by=authorized_by,
        success_criteria=success_list,
        constraints=constraints_list,
        task_id=task_id or None,
    )

    return _json.dumps({
        "task_id": tid,
        "goal": goal,
        "scope": scope_list,
        "authorized_by": authorized_by,
        "success_criteria": success_list,
        "constraints": constraints_list,
        "status": "in_progress",
        "message": (
            f"Task '{goal[:60]}' declared. Pass task_id='{tid}' to all "
            "sentigent_evaluate() calls for this task."
        ),
    }, indent=2)


@_tool()
def sentigent_complete_task(
    task_id: str,
    outcome: str = "",
    summary: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Mark a task as complete after all actions are done.

    Call this when a task is finished (or abandoned). Records the task-level
    outcome which feeds the pattern miner and syncs to Layer 2 for org-wide
    learning at the task level (not just individual episodes).

    Args:
        task_id: The task_id returned by sentigent_start_task()
        outcome: 'correct' if task succeeded, 'incorrect' if it failed,
                 empty string if outcome is unknown/abandoned
        summary: Optional human-readable summary of what was accomplished
        agent_id: Optional agent identifier
        profile: Optional profile name

    Returns:
        JSON confirmation of task completion.
    """
    import json as _json

    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    judge.complete_task(
        task_id=task_id,
        outcome=outcome or None,
        summary=summary or None,
    )

    return _json.dumps({
        "task_id": task_id,
        "outcome": outcome or "abandoned",
        "summary": summary or None,
        "status": "complete",
        "message": f"Task {task_id[:8]}... marked as {outcome or 'abandoned'}.",
    }, indent=2)


@_tool()
def sentigent_active_tasks(
    agent_id: str = "",
    profile: str = "",
) -> str:
    """List all currently in-progress tasks for this agent.

    Useful for dark-factory multi-agent scenarios: see what tasks are declared,
    their scope, and how many actions have been taken so far.

    Returns:
        JSON list of in-progress tasks with scope, goal, and episode counts.
    """
    import json as _json

    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    tasks = judge._memory.list_active_tasks()

    return _json.dumps({
        "active_task_count": len(tasks),
        "tasks": tasks,
    }, indent=2)


@_tool()
def sentigent_add_relationship(
    from_entity: str,
    from_type: str,
    relationship: str,
    to_entity: str,
    to_type: str,
    weight: float = 1.0,
    metadata: str = "{}",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Add an entity relationship to the org knowledge graph.

    Relationships teach Sentigent about the org's structure: who owns what,
    what services depend on each other, who approves changes to which files.
    This context is surfaced by ContextAssembler during evaluations so the
    judgment engine understands the blast radius and approval chains for actions.

    Relationship types:
        DEPENDS_ON    — A requires B to function
        REFERENCED_BY — A is referenced/called by B
        OWNED_BY      — A is owned/maintained by B (usually member)
        APPROVES      — A (member/team) must approve changes to B
        REVIEWS       — A (member/team) reviews changes to B
        DEPLOYED_WITH — A and B are deployed together
        CALLS         — A invokes B at runtime
        STORES_IN     — A stores data in B (database/service)
        TRIGGERS      — A triggers B (event/webhook/job)

    Entity types: file, service, member, team, database, infra

    Args:
        from_entity: Source entity name (e.g. "auth/middleware.py", "payment-service")
        from_type: Source entity type ("file", "service", "member", "team", etc.)
        relationship: Relationship type (OWNED_BY, DEPENDS_ON, etc.)
        to_entity: Target entity name (e.g. "alice@company.com", "postgres-prod")
        to_type: Target entity type
        weight: Relationship strength 0.0–1.0 (default 1.0)
        metadata: JSON string with extra context (e.g. '{"note": "primary owner"}')

    Returns:
        JSON with success status and the stored relationship.
    """
    import json as _json
    import os as _os

    try:
        meta = _json.loads(metadata) if metadata else {}
    except Exception:
        meta = {}

    supabase_url = _os.environ.get("SUPABASE_URL", "")
    has_key = bool(
        _os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or _os.environ.get("SUPABASE_ANON_KEY")
    )
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    org_id = judge._org_id

    if not supabase_url or not has_key or not org_id:
        return _json.dumps({
            "success": False,
            "error": "Supabase not configured or org_id missing.",
        })

    try:
        from sentigent.sync.manager import _get_supabase_client as _get_sb
        from sentigent.core.context_assembler import ContextAssembler
        client = _get_sb()
        assembler = ContextAssembler(client, org_id)
        ok = assembler.add_relationship(
            from_entity=from_entity,
            from_type=from_type,
            relationship=relationship,
            to_entity=to_entity,
            to_type=to_type,
            weight=weight,
            metadata=meta,
        )
        if ok:
            return _json.dumps({
                "success": True,
                "relationship": {
                    "from": f"{from_type}:{from_entity}",
                    "relationship": relationship,
                    "to": f"{to_type}:{to_entity}",
                    "weight": weight,
                },
            }, indent=2)
        return _json.dumps({"success": False, "error": "upsert failed"})
    except Exception as exc:
        return _json.dumps({"success": False, "error": str(exc)})


@_tool()
def sentigent_get_relationships(
    entity: str = "",
    relationship: str = "",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Query the org relationship graph.

    Shows what Sentigent knows about entity dependencies, ownership, and
    approval chains. Used by ContextAssembler during evaluations — inspect
    it here to verify the graph is populated correctly.

    Args:
        entity: Filter to relationships involving this entity (partial match)
        relationship: Filter by relationship type (OWNED_BY, DEPENDS_ON, etc.)

    Returns:
        JSON list of matching relationship edges.
    """
    import json as _json
    import os as _os

    supabase_url = _os.environ.get("SUPABASE_URL", "")
    has_key = bool(
        _os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or _os.environ.get("SUPABASE_ANON_KEY")
    )
    judge = _get_judge(agent_id=agent_id or None, profile=profile or None)
    org_id = judge._org_id

    if not supabase_url or not has_key or not org_id:
        return _json.dumps({"relationships": [], "error": "Supabase not configured"})

    try:
        from sentigent.sync.manager import _get_supabase_client as _get_sb
        client = _get_sb()
        q = (
            client.table("org_relationships")
            .select("from_entity,from_type,relationship,to_entity,to_type,weight,metadata,created_at")
            .eq("org_id", org_id)
        )
        if relationship:
            q = q.eq("relationship", relationship.upper())
        q = q.order("created_at", desc=True).limit(100)
        resp = q.execute()
        rows = resp.data or []

        if entity:
            entity_lower = entity.lower()
            rows = [
                r for r in rows
                if entity_lower in r["from_entity"].lower()
                or entity_lower in r["to_entity"].lower()
            ]

        return _json.dumps({
            "relationship_count": len(rows),
            "relationships": rows,
        }, indent=2)
    except Exception as exc:
        return _json.dumps({"relationships": [], "error": str(exc)})


@_tool()
def sentigent_observe(
    text: str,
    member_identifier: str = "",
    member_type: str = "human",
    tool_used: str = "",
    outcome: str = "",
    was_escalated: bool = False,
) -> str:
    """Feed a human–agent conversation or interaction into the org world model.

    Use this to manually submit conversation text, task descriptions, or
    individual interactions so the world model can extract vocabulary,
    identify entities, and build member context.

    The world model automatically captures from synced episodes, but this
    tool lets you explicitly feed in conversations, Slack messages, ticket
    descriptions, or any text that represents org knowledge.

    Args:
        text: The conversation or interaction text to process
        member_identifier: Email or ID of the person/agent (optional)
        member_type: 'human' or 'agent' (default: 'human')
        tool_used: Which tool was used in this interaction (optional)
        outcome: 'correct' | 'incorrect' | '' (optional)
        was_escalated: Whether this interaction was escalated (default: False)

    Returns:
        JSON confirming what was extracted from the observation.
    """
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    if not resolved_org_id:
        return json.dumps({
            "status": "unavailable",
            "reason": "SENTIGENT_ORG_ID not set",
        }, indent=2)

    try:
        from sentigent.sync.manager import _get_supabase_client as _get_sb
        from sentigent.memory.world_model import WorldModelBuilder

        client = _get_sb()
        builder = WorldModelBuilder(client, resolved_org_id)
        builder.process_conversation(
            member_identifier=member_identifier or "anonymous",
            member_type=member_type,
            text=text,
            tool_used=tool_used,
            outcome=outcome or None,
            was_escalated=was_escalated,
        )
        counts = builder.flush()
        return json.dumps({
            "status": "ok",
            "observed": text[:100] + ("..." if len(text) > 100 else ""),
            "extracted": counts,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_attribution_report(
    agent_id: str = "",
    days: int = 90,
) -> str:
    """Outcome Attribution: connect instruction clarity to agent outcomes.

    Analyzes stored episodes to learn which types of tasks (by domain × specificity)
    lead to correct vs incorrect outcomes. Tells you: "Do clearer instructions
    actually lead to better results for this team?"

    Also runs backfill to score any historical episodes that haven't been
    clarity-scored yet.

    Args:
        agent_id: Agent to analyze (default: from env)
        days: Look-back window in days (default: 90)

    Returns:
        JSON with:
        - patterns: list of learned domain × specificity → outcome_rate patterns
        - conversation_intelligence: clarity metrics for prove command
        - estimated_monthly_savings_usd: ROI estimate from avoided rework

    Example output::
        {
          "patterns": [
            {
              "domain": "auth",
              "specificity_bucket": "low",
              "outcome_rate": 0.27,
              "incorrect_rate": 0.73,
              "insight": "⚠️ High risk: auth tasks with low specificity almost always fails"
            }
          ],
          "conversation_intelligence": {
            "avg_clarity_score": 0.52,
            "low_clarity_incorrect_outcomes": 14,
            "estimated_rework_avoided": 14
          },
          "estimated_monthly_savings_usd": 890.0
        }
    """
    resolved_agent_id = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "default")
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    try:
        from sentigent.memory.store import MemoryStore
        from sentigent.core.outcome_attributor import OutcomeAttributor

        store = MemoryStore(agent_id=resolved_agent_id, org_id=resolved_org_id)
        attr = OutcomeAttributor(
            db_path=store.db_path,
            agent_id=resolved_agent_id,
            org_id=resolved_org_id,
        )

        # Backfill historical episodes without clarity data
        backfilled = attr.backfill_clarity(limit=200)

        report = attr.analyze(days=days)
        result = report.to_dict()
        result["backfilled_episodes"] = backfilled
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_add_graph_policy(
    name: str,
    enforce_action: str,
    enforce_reason: str,
    severity: str = "high",
    match_entity_type: str = "file",
    match_relationship: str = "TAGGED",
    match_tag: str = "",
    match_task_pattern: str = "",
    description: str = "",
) -> str:
    """Add a graph-based policy to the org policy engine (Phase 6B).

    Graph policies fire when an action touches an entity (file, service, database)
    that has a specific relationship in the org knowledge graph — e.g., "escalate
    any action touching a payment-critical file."

    Unlike flat pattern matching, graph policies compose naturally:
    - A file tagged 'payment-critical' triggers the payment policy
    - That same file can ALSO have a 'DEPENDS_ON' relationship triggering a
      dependency policy — without you writing a combined regex

    Args:
        name: Unique policy name (e.g., "payment-critical-files")
        enforce_action: Action to enforce: "escalate" | "slow_down" | "enrich" | "block"
        enforce_reason: Human-readable reason shown to the agent
        severity: "low" | "medium" | "high" | "critical"
        match_entity_type: Entity type to match: "file" | "service" | "database" | ""
        match_relationship: Relationship type: "TAGGED" | "DEPENDS_ON" | "OWNED_BY" | ""
        match_tag: Tag value on the 'to_entity' end of the relationship
        match_task_pattern: Optional regex that must also match the task description
        description: Human-readable description of this policy

    Returns:
        JSON confirming the policy was added.

    Example — escalate any action touching payment-critical files::
        sentigent_add_graph_policy(
            name="payment-critical-files",
            enforce_action="escalate",
            enforce_reason="Payment-critical file touched — human review required",
            severity="critical",
            match_entity_type="file",
            match_relationship="TAGGED",
            match_tag="payment-critical",
        )
    """
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    valid_actions = {"escalate", "slow_down", "enrich", "block"}
    if enforce_action not in valid_actions:
        return json.dumps({
            "status": "error",
            "error": f"enforce_action must be one of {sorted(valid_actions)}",
        }, indent=2)

    try:
        from sentigent.memory.store import MemoryStore
        from sentigent.core.graph_policy import GraphPolicyEngine, GraphPolicy

        store = MemoryStore(
            agent_id=os.environ.get("SENTIGENT_AGENT_ID", "default"),
            org_id=resolved_org_id,
        )
        gpe = GraphPolicyEngine(db_path=store.db_path, org_id=resolved_org_id)
        policy = GraphPolicy(
            name=name,
            description=description,
            match_entity_type=match_entity_type,
            match_relationship=match_relationship,
            match_tag=match_tag,
            match_task_pattern=match_task_pattern,
            enforce_action=enforce_action,
            enforce_reason=enforce_reason,
            severity=severity,
        )
        ok = gpe.add_policy(policy)
        return json.dumps({
            "status": "ok" if ok else "error",
            "policy": policy.to_dict(),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_graph_policies() -> str:
    """List all active graph-based policies for this org.

    Returns:
        JSON list of all graph policies with their match conditions and actions.
    """
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    try:
        from sentigent.memory.store import MemoryStore
        from sentigent.core.graph_policy import GraphPolicyEngine

        store = MemoryStore(
            agent_id=os.environ.get("SENTIGENT_AGENT_ID", "default"),
            org_id=resolved_org_id,
        )
        gpe = GraphPolicyEngine(db_path=store.db_path, org_id=resolved_org_id)
        policies = gpe.list_policies()
        return json.dumps({
            "status": "ok",
            "count": len(policies),
            "policies": [p.to_dict() for p in policies],
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_backfill_clarity(
    agent_id: str = "",
    limit: int = 200,
) -> str:
    """Backfill clarity scores for historical episodes that don't have them yet.

    Scores existing episodes in the local SQLite store with:
    - clarity_score (CLEAR framework, 0.0–1.0)
    - task_specificity (intent extractor, 0.0–1.0)
    - task_domain (deploy/auth/data/finance/comms/general)

    This enables the Outcome Attributor to analyze historical data.

    Args:
        agent_id: Agent to backfill (default: from env)
        limit: Max episodes to score per call (default: 200)

    Returns:
        JSON with count of episodes backfilled.
    """
    resolved_agent_id = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "default")
    resolved_org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    try:
        from sentigent.memory.store import MemoryStore
        from sentigent.core.outcome_attributor import OutcomeAttributor

        store = MemoryStore(agent_id=resolved_agent_id, org_id=resolved_org_id)
        attr = OutcomeAttributor(
            db_path=store.db_path,
            agent_id=resolved_agent_id,
            org_id=resolved_org_id,
        )
        n = attr.backfill_clarity(limit=limit)
        return json.dumps({"status": "ok", "episodes_backfilled": n}, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_analyze_task(
    task: str,
    conversation_history: list[str] | None = None,
) -> str:
    """Analyze a task description for clarity and extract structured intent.

    Combines the CLEAR framework clarity scorer with the intent extractor.
    Use this before sentigent_start_task() to understand if the task is
    specific enough and what scope/goal/criteria would be auto-extracted.

    Args:
        task: The natural language task description to analyze.
        conversation_history: Optional prior conversation turns for context
            and pronoun resolution.

    Returns:
        JSON with clarity score, gaps, structured intent, and suggested
        sentigent_start_task() parameters.

    Example::
        sentigent_analyze_task("fix the auth stuff")
        # → clarity.level = "low", gaps = ["No file...", "No success criteria..."]
        # → suggestion: "Which file? What does success look like?"
    """
    try:
        from sentigent.core.clarity_scorer import ClarityScorer
        from sentigent.core.intent_extractor import IntentExtractor

        scorer = ClarityScorer()
        extractor = IntentExtractor()

        history = conversation_history or []
        clarity = scorer.score(task, history)
        intent = extractor.extract(task, history)

        return json.dumps({
            "task": task,
            "clarity": clarity.to_dict(),
            "intent": intent.to_dict(),
            "suggested_start_task": intent.to_start_task_kwargs(),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


@_tool()
def sentigent_session_health(
    turns: list[str],
) -> str:
    """Compute the health score for the current session's human-agent interaction.

    Aggregates four signals into an overall health score (0.0–1.0):
      - Clarity score (avg over user turns) × 0.25
      - Convergence rate (1 - correction_loops/turns) × 0.30
      - Friction absence × 0.25
      - Intent stability (how consistent the goal has been) × 0.20

    Use this to proactively surface interaction quality issues and suggest
    interventions before they compound.

    Args:
        turns: List of conversation turns. Can be all turns mixed (user + agent).

    Returns:
        JSON with health score, level, component scores, friction events,
        and top intervention recommendation.

    Example::
        sentigent_session_health(["fix auth", "which file?", "auth.py", "fix what?"])
        # → health_score = 0.42, level = "poor"
        # → top_intervention = "Agent repeated clarification question..."
    """
    try:
        from sentigent.core.clarity_scorer import ClarityScorer
        from sentigent.core.friction_detector import FrictionDetector

        if not turns:
            return json.dumps({
                "health_score": 1.0,
                "level": "excellent",
                "message": "No turns to analyze",
            }, indent=2)

        scorer = ClarityScorer()
        detector = FrictionDetector()

        # Score clarity on all turns (treat each as a potential task statement)
        clarity_scores = [scorer.score(t).overall for t in turns if t.strip()]
        avg_clarity = sum(clarity_scores) / len(clarity_scores) if clarity_scores else 0.5

        # Friction analysis
        friction_events = detector.analyze(turns)
        friction_summary = detector.session_summary(friction_events)
        friction_absence = friction_summary["friction_absence_score"]

        # Convergence: how much correction loop vs total turns
        correction_count = friction_summary["by_type"].get("correction_loop", 0)
        convergence = max(0.0, 1.0 - (correction_count / max(len(turns), 1)))

        # Intent stability: check if user turns are consistent (simple heuristic)
        from sentigent.core.intent_extractor import IntentExtractor
        extractor = IntentExtractor()
        specificities = [extractor.extract(t).specificity for t in turns if t.strip()]
        intent_stability = (
            1.0 - (max(specificities) - min(specificities))
            if len(specificities) > 1
            else 0.7
        )
        intent_stability = max(0.0, min(1.0, intent_stability))

        health_score = (
            avg_clarity * 0.25
            + convergence * 0.30
            + friction_absence * 0.25
            + intent_stability * 0.20
        )
        health_score = round(max(0.0, min(1.0, health_score)), 3)

        if health_score >= 0.80:
            level = "excellent"
        elif health_score >= 0.60:
            level = "good"
        elif health_score >= 0.40:
            level = "fair"
        else:
            level = "poor"

        return json.dumps({
            "health_score": health_score,
            "level": level,
            "turns_analyzed": len(turns),
            "components": {
                "avg_clarity": round(avg_clarity, 3),
                "convergence": round(convergence, 3),
                "friction_absence": round(friction_absence, 3),
                "intent_stability": round(intent_stability, 3),
            },
            "friction": friction_summary,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)


def _get_supabase():
    """Return a Supabase client using env vars, or None if unavailable."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        # Try loading from .env file next to sentigent package
        import pathlib
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip("\"'")
                if k not in os.environ:
                    os.environ[k] = v
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


@_tool()
def sentigent_remember(
    content: str,
    type: str = "convention",
    project: str = "",
    confidence: float = 1.0,
    agent_id: str = "",
) -> str:
    """Capture a team convention, decision, pitfall, or pattern into organizational memory.

    Use this to persist knowledge that should appear in future session briefings.
    The knowledge will be injected at the start of every relevant session.

    Args:
        content: The knowledge to capture (be specific — vague entries are less useful)
        type: One of: convention | decision | pitfall | pattern
        project: Project slug to scope the knowledge (e.g. "scrollbookproject"), or empty for global
        confidence: Initial confidence score 0.0-1.0 (default 1.0 for manually entered knowledge)
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)
    """
    valid_types = ("convention", "decision", "pitfall", "pattern")
    if type not in valid_types:
        return json.dumps({"error": f"type must be one of: {', '.join(valid_types)}"})

    if not content.strip():
        return json.dumps({"error": "content cannot be empty"})

    org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    if not org_id:
        return json.dumps({"error": "SENTIGENT_ORG_ID not set — cannot save team knowledge"})

    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")

    db = _get_supabase()
    if not db:
        return json.dumps({"error": "Supabase not configured — check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in sentigent/.env"})

    try:
        row = {
            "org_id": org_id,
            "agent_id": aid,
            "project_slug": project.strip() or None,
            "type": type,
            "content": content.strip(),
            "confidence": max(0.0, min(1.0, confidence)),
            "source": "manual",
        }
        result = db.table("team_knowledge").insert(row).execute()
        inserted = result.data[0] if result.data else row
        scope = f"project={project}" if project else "global"
        return json.dumps({
            "saved": True,
            "id": inserted.get("id", ""),
            "type": type,
            "scope": scope,
            "message": f"Captured as {type} ({scope}). Will appear in future session briefings.",
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def sentigent_briefing(
    project: str = "",
) -> str:
    """Pull the current team knowledge briefing for a project (or global).

    Returns the same briefing that would be injected at session start.
    Useful for checking what knowledge Sentigent has about a project.

    Args:
        project: Project slug (e.g. "scrollbookproject"), or empty for global-only
    """
    org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    if not org_id:
        return json.dumps({"error": "SENTIGENT_ORG_ID not set"})

    db = _get_supabase()
    if not db:
        return json.dumps({"briefing": "", "rows": 0, "error": "Supabase not configured"})

    try:
        result = db.table("team_knowledge").select(
            "type, content, confidence, project_slug"
        ).eq("org_id", org_id).order("confidence", desc=True).limit(50).execute()

        rows = result.data or []
        project_slug = project.strip() or None

        filtered = [
            r for r in rows
            if r.get("project_slug") is None
            or (project_slug and r.get("project_slug") == project_slug)
        ]

        if not filtered:
            return json.dumps({
                "briefing": "No team knowledge found. Use sentigent_remember() to add conventions, decisions, pitfalls, or patterns.",
                "rows": 0,
            })

        # Group by type
        by_type: dict[str, list[str]] = {"convention": [], "decision": [], "pitfall": [], "pattern": []}
        for r in filtered:
            t = r.get("type", "convention")
            if t in by_type:
                by_type[t].append(r.get("content", ""))

        lines = [f"## Sentigent Team Briefing — {project_slug or 'global'}", ""]
        for label, items in [
            ("Team Conventions", by_type["convention"]),
            ("Recent Decisions", by_type["decision"]),
            ("Known Pitfalls", by_type["pitfall"]),
            ("Learned Patterns", by_type["pattern"]),
        ]:
            if items:
                lines.append(f"### {label}")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")

        return json.dumps({
            "briefing": "\n".join(lines),
            "rows": len(filtered),
            "breakdown": {t: len(v) for t, v in by_type.items()},
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def sentigent_route(
    task_text: str,
    agent_id: str = "",
) -> str:
    """Suggest the best skill, agent, and model for a task using learned routing history.

    Uses a 4-step resolution chain:
      1. Learned patterns from past episodes (most specific)
      2. Embedding similarity match against routing seed data
      3. Falls through to static defaults if no match found

    Args:
        task_text: Description of the task or prompt to route
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var)

    Returns:
        JSON with skill, agent, model, confidence, source, and all candidate matches
    """
    judge = _get_judge(agent_id=agent_id or None)

    # Step 1: Check learned patterns from past episodes
    try:
        from sentigent.memory.store import MemoryStore
        store = MemoryStore(
            agent_id=judge._agent_id,
            org_id=judge._org_id,
            db_path=getattr(judge, "_db_path", None),
        )
    except Exception as exc:
        return json.dumps({"error": f"store init failed: {exc}"})

    # Step 2: Embedding similarity match
    try:
        from sentigent.routing.matcher import match_seeds
        matches = match_seeds(task_text, store)
    except Exception:
        matches = []

    if matches:
        best = matches[0]
        return json.dumps({
            "skill": best.skill,
            "agent": best.agent,
            "model": best.model,
            "confidence": round(best.confidence, 4),
            "task_type": best.task_type,
            "source": best.source,
            "candidates": [
                {
                    "skill": m.skill,
                    "agent": m.agent,
                    "model": m.model,
                    "confidence": round(m.confidence, 4),
                    "task_type": m.task_type,
                }
                for m in matches
            ],
        }, indent=2)

    # Step 3: Static defaults — return routing skeleton without a match
    return json.dumps({
        "skill": None,
        "agent": "general-purpose",
        "model": "sonnet",
        "confidence": 0.0,
        "task_type": "unknown",
        "source": "static_default",
        "candidates": [],
        "hint": "No embedding match found. Use skill-router for triage.",
    }, indent=2)


@_tool()
def sentigent_intent(
    task: str,
    context: str = "{}",
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Synthesize a SENTIGENT_INTENT context block from memory + routing + org patterns.

    Call this at session start (before the first tool call) to inject structured
    intent context. The returned intent_block string can be prepended to the agent's
    system prompt or task context.

    Args:
        task: Natural language description of what the session should accomplish.
        context: JSON string with extra context (branch, environment, etc.).
        agent_id: Optional agent identifier (defaults to SENTIGENT_AGENT_ID env var).
        profile: Optional profile name (defaults to SENTIGENT_PROFILE env var).

    Returns:
        JSON with intent_block (YAML string for injection) and all parsed fields.
    """
    try:
        judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

        from sentigent.memory.store import MemoryStore
        from sentigent.core.intent_synthesizer import IntentSynthesizer

        store = MemoryStore(
            agent_id=judge._agent_id,
            org_id=judge._org_id,
            db_path=getattr(judge, "_db_path", None),
        )

        sync = None
        try:
            from sentigent.sync.manager import SyncManager
            sync = SyncManager(
                org_id=judge._org_id,
                agent_id=judge._agent_id,
                db_path=getattr(judge, "_db_path", None),
            )
        except Exception:
            pass

        ctx = {}
        if context:
            try:
                ctx = json.loads(context)
            except Exception:
                pass

        block = IntentSynthesizer().synthesize(
            task=task,
            context=ctx,
            store=store,
            sync_manager=sync,
        )

        return json.dumps({
            "intent_block": block.to_context_block(),
            **block.to_dict(),
        }, indent=2)

    except Exception as exc:
        return json.dumps({"error": str(exc), "intent_block": ""})


@_tool()
def sentigent_setup_agent(
    action: str = "status",
    change_id: int = 0,
    agent_id: str = "",
    profile: str = "",
) -> str:
    """Autonomous Setup Agent — observe, detect drift, apply corrections, revert.

    Actions:
      status        — show applied changes, revert rate, autonomy stage, pending recommendations
      detect        — run DriftDetector on last 50 observations and surface events
      apply_drift   — detect drift and apply all corrections (Apply+Undo, stage 1 default)
      revert N      — undo change with id=N (pass change_id=N)
      revert_all    — revert all non-reverted changes from last 7 days
      approve_upgrade — upgrade to stage 2 full autonomy if eligible

    Args:
        action: One of: status, detect, apply_drift, revert, revert_all, approve_upgrade
        change_id: Required for action="revert" — the ID of the change to undo
        agent_id: Optional agent identifier
        profile: Optional profile name

    Returns:
        JSON with results of the requested action.
    """
    try:
        judge = _get_judge(agent_id=agent_id or None, profile=profile or None)

        from sentigent.memory.store import MemoryStore
        from sentigent.setup.observer import SetupObserver
        from sentigent.setup.drift_detector import DriftDetector
        from sentigent.setup.writer import SetupWriter
        from sentigent.setup.revert_tracker import RevertRateTracker

        store = MemoryStore(
            agent_id=judge._agent_id,
            org_id=judge._org_id,
            db_path=getattr(judge, "_db_path", None),
        )

        observer = SetupObserver(store)
        detector = DriftDetector()
        writer = SetupWriter(store)
        tracker = RevertRateTracker(store)

        if action == "status":
            tracker_status = tracker.get_status()
            changes = store.get_setup_changes(limit=10, include_reverted=False)
            return json.dumps({
                "action": "status",
                **tracker_status,
                "recent_changes": changes,
            }, indent=2)

        if action == "detect":
            window = observer.get_window(size=50)
            events = detector.detect(window)
            return json.dumps({
                "action": "detect",
                "observations_analyzed": len(window),
                "drift_events": [
                    {
                        "drift_type": e.drift_type,
                        "severity": e.severity,
                        "description": e.description,
                        "recommendation": e.recommendation,
                    }
                    for e in events
                ],
            }, indent=2)

        if action == "apply_drift":
            window = observer.get_window(size=50)
            events = detector.detect(window)
            applied = []
            for event in events:
                cid = writer.apply(event)
                applied.append({
                    "change_id": cid,
                    "drift_type": event.drift_type,
                    "severity": event.severity,
                    "description": event.description,
                    "recommendation": event.recommendation,
                })
            return json.dumps({
                "action": "apply_drift",
                "applied_count": len(applied),
                "changes": applied,
                "note": "Each change is reversible via sentigent_setup_agent(action='revert', change_id=N)",
            }, indent=2)

        if action == "revert":
            if change_id <= 0:
                return json.dumps({"error": "change_id required for action='revert'"})
            ok = writer.revert(change_id)
            return json.dumps({
                "action": "revert",
                "change_id": change_id,
                "success": ok,
            }, indent=2)

        if action == "revert_all":
            changes = store.get_setup_changes(limit=200, include_reverted=False)
            reverted = []
            for c in changes:
                if writer.revert(c["id"]):
                    reverted.append(c["id"])
            result: dict = {
                "action": "revert_all",
                "reverted_ids": reverted,
                "reverted_count": len(reverted),
                "total_non_reverted_fetched": len(changes),
            }
            if len(changes) >= 200:
                result["warning"] = "Fetched limit of 200 changes — older changes may not have been reverted."
            return json.dumps(result, indent=2)

        if action == "approve_upgrade":
            ok = tracker.upgrade_to_stage_2()
            return json.dumps({
                "action": "approve_upgrade",
                "success": ok,
                "message": (
                    "Autonomy upgraded to stage 2 — setup agent now applies changes without undo prompts."
                    if ok else
                    "Not eligible yet. Check status for revert_rate and applied count."
                ),
            }, indent=2)

        return json.dumps({"error": f"Unknown action: {action}. Valid: status, detect, apply_drift, revert, revert_all, approve_upgrade"})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Clone tools — "The Clone Speaks" in-session surface (the operator's front door).
# These let you operate your clone conversationally inside Claude Code, instead of
# dropping to CLI scripts. Same logic as scripts/*.py; this is the product surface.
# ─────────────────────────────────────────────────────────────────────────────

def _clone_store(agent_id: str = "", org_id: str = ""):
    from sentigent.memory.store import MemoryStore

    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    oid = org_id or os.environ.get("SENTIGENT_ORG_ID", "default")
    return MemoryStore(agent_id=aid, org_id=oid)


@_tool()
def clone_status(agent_id: str = "", org_id: str = "") -> str:
    """Show how much of YOU your clone has captured — the Clone Readiness gauge.

    Returns the readiness %, the component breakdown (profile, decision signal,
    practices), and the single next move that grows the clone most. Read-only.
    """
    from sentigent.core import clone_readiness

    try:
        r = clone_readiness.compute(_clone_store(agent_id, org_id))
        return json.dumps(r.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def clone_briefing(agent_id: str = "", org_id: str = "") -> str:
    """The clone's in-session greeting: readiness, what it learned about you, and
    one next move. Same briefing shown at session start. Markdown. Read-only."""
    from sentigent.core.briefing import build_clone_briefing

    try:
        text = build_clone_briefing(_clone_store(agent_id, org_id))
        return text or "Your clone has nothing to report yet — keep working and it learns."
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def clone_review(agent_id: str = "", org_id: str = "") -> str:
    """Review your clone vs best practices: the GOOD (strengths to keep), the BAD
    (tensions/anti-patterns), and MISSING gaps you can adopt. Uses the local LLM
    for the qualitative read; falls back to deterministic if it's offline.

    To adopt a suggested gap, call clone_adopt(n) with its number.
    """
    from sentigent.core import profile_review

    try:
        r = profile_review.review(_clone_store(agent_id, org_id))
        return json.dumps(r.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def clone_adopt(n: int, agent_id: str = "", org_id: str = "") -> str:
    """Improve your clone: adopt gap #n from clone_review into your practices
    playbook. Raises best-practice coverage and clone readiness. n is 1-based.
    """
    from sentigent.core import profile_review

    try:
        store = _clone_store(agent_id, org_id)
        r = profile_review.review(store, use_llm=False)
        if not (1 <= n <= len(r.gaps)):
            return json.dumps({"error": f"No gap #{n}. There are {len(r.gaps)} gaps. Call clone_review first."})
        g = r.gaps[n - 1]
        pid = store.add_practice(g.statement, domain=g.domain, cadence=g.cadence)
        after = profile_review.review(store, use_llm=False)
        return json.dumps({
            "adopted": {"id": pid, "statement": g.statement, "domain": g.domain,
                        "cadence": g.cadence, "why": g.rationale},
            "coverage_before": r.coverage_pct,
            "coverage_after": after.coverage_pct,
            "message": f"Adopted into your playbook. Best-practice coverage {r.coverage_pct}% → {after.coverage_pct}%.",
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def clone_journey(agent_id: str = "", org_id: str = "") -> str:
    """Show where you are across the 5-step clone lifecycle + the single next move.

    Renders a ladder (Create → Review → Improve → Reverse-shadow → Fly) with
    ✅/▶️/🔒 per step from real signal, your readiness %, any open escalations, and
    the most valuable next move. Deterministic, no LLM, read-only.
    """
    from sentigent.core.journey import compute_journey

    try:
        j = compute_journey(_clone_store(agent_id, org_id))
        return j.render() + "\n\n```json\n" + json.dumps(j.to_dict(), indent=2) + "\n```"
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Operator tools — Fly mode (Step 5) in-session. Dry-run by default: the whole
# loop runs (drive → risk → gate → escalate → verify → checkpoint, all persisted)
# without touching anything, so you watch it before it acts. execute=True flips
# the worker to real `claude -p` in an isolated git worktree.
# ─────────────────────────────────────────────────────────────────────────────

@_tool()
def operator_start(plan: str = "", goal: str = "", autonomy: str = "assisted",
                   budget_usd: float = 2.0, execute: bool = False,
                   agent_id: str = "", org_id: str = "") -> str:
    """Run a plan AS you. Give a markdown plan (checkbox/numbered list) OR a one-line
    goal. Returns a digest: which steps it did, where it would stop to ask you, and
    the run id. DRY-RUN by default (execute=False) — nothing changes; the judgment
    + escalation loop still runs so you can watch. autonomy: copilot|assisted|autopilot|trusted.
    """
    from sentigent.operator.operate import operate
    from sentigent.operator.plan import parse_plan

    try:
        if plan.strip():
            p = parse_plan(plan)
        elif goal.strip():
            p = parse_plan(f"- {goal}", goal=goal)
        else:
            return json.dumps({"error": "give a `plan` (markdown) or a `goal`"})
        if not p.pending:
            return json.dumps({"error": "no pending steps found in that plan"})

        store = _clone_store(agent_id, org_id)
        worktree = None
        repo_path = None
        if execute:
            from sentigent.operator.worktree import WorktreeManager
            repo_path = os.environ.get("SENTIGENT_OPERATOR_REPO", os.getcwd())
            worktree = WorktreeManager(repo_path)

        res = operate(store, p, autonomy=autonomy, budget_usd=budget_usd,
                      execute=execute, worktree=worktree, repo_path=repo_path)
        return res.digest() + "\n\n" + json.dumps(res.to_dict())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_loop(goal: str, plan: str = "", autonomy: str = "autopilot",
                  budget_usd: float = 5.0, max_laps: int = 8,
                  dod_test_cmd: str = "", dod_files: str = "", dod_grep: str = "",
                  dod_objective: str = "", execute: bool = False,
                  agent_id: str = "", org_id: str = "") -> str:
    """Run a GOAL to its definition-of-done in a self-driving LOOP (the dark factory).

    Unlike operator_start (one linear pass), this laps with a FRESH worker each
    time until the goal-level DoD holds. When it hits a soft blocker, your CLONE
    (local Gemma + your profile + past precedents) answers it AS YOU instead of
    paging you — it only stops to ask when genuinely unsure or on a hard rule
    (push/prod/rm/secrets). Every answer you give trains the clone so that class of
    blocker is auto-resolved next time. Autonomy compounds.

    DoD (the stop condition) from any of: dod_test_cmd, dod_files (comma-sep),
    dod_grep ("pattern::path"), dod_objective (NL, model-judged). DRY-RUN by default.
    """
    from sentigent.operator.goal_dod import GoalDoD
    from sentigent.operator.loop import run_loop
    from sentigent.operator.plan import parse_plan

    try:
        p = parse_plan(plan) if plan.strip() else parse_plan(f"- {goal}", goal=goal)
        if not p.pending:
            return json.dumps({"error": "no pending steps in that plan/goal"})

        criteria: dict = {}
        if dod_test_cmd.strip():
            criteria["test_cmd"] = dod_test_cmd.strip()
        if dod_files.strip():
            criteria["files_exist"] = [f.strip() for f in dod_files.split(",") if f.strip()]
        if dod_grep.strip() and "::" in dod_grep:
            pat, _, path = dod_grep.partition("::")
            criteria["grep"] = {"pattern": pat.strip(), "path": path.strip()}
        if dod_objective.strip():
            criteria["objective"] = dod_objective.strip()

        store = _clone_store(agent_id, org_id)
        repo_path = os.environ.get("SENTIGENT_OPERATOR_REPO", os.getcwd())
        dod = GoalDoD(goal, criteria=criteria)
        res = run_loop(store, goal, dod, plan=p, repo_path=repo_path,
                       max_laps=max_laps, autonomy=autonomy, budget_usd=budget_usd,
                       execute=execute)
        return res.digest() + "\n\n" + json.dumps(res.to_dict())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_resume(run_id: int, agent_id: str = "", org_id: str = "") -> str:
    """Resume a paused operator run after you answered its escalation (operator_answer).
    Reconstructs the plan + step state from the run, applies your decision to the step
    it paused on (approve → run it · skip → mark skipped · takeover → hand you the
    worktree), and continues over the remaining pending steps under the SAME run id —
    it does NOT restart from step 1. Honors execute mode (real `claude -p` in the run's
    worktree) if that's how the run started. Returns the same digest as operator_start.
    """
    from sentigent.operator.operate import operate
    from sentigent.operator.plan import Plan

    try:
        store = _clone_store(agent_id, org_id)
        run = store.get_run(run_id)
        if not run:
            return json.dumps({"error": f"no run #{run_id}"})

        execute = bool(run.get("worktree"))
        worktree = None
        repo_path = None
        if execute:
            from sentigent.operator.worktree import WorktreeManager
            repo_path = os.environ.get("SENTIGENT_OPERATOR_REPO", os.getcwd())
            worktree = WorktreeManager(repo_path)

        # operate() rebuilds the plan from the run when resume_run_id is set, so the
        # passed plan is ignored — pass an empty placeholder.
        res = operate(store, Plan(goal="(resumed)", steps=[]),
                      autonomy=str(run.get("autonomy_level", "assisted")),
                      budget_usd=float(run.get("budget_usd", 2.0) or 2.0),
                      execute=execute, worktree=worktree, repo_path=repo_path,
                      resume_run_id=run_id)
        return res.digest() + "\n\n" + json.dumps(res.to_dict())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_status(run_id: int, agent_id: str = "", org_id: str = "") -> str:
    """Show a run's status: the audit-log events (newest first) and any open
    escalations waiting on your answer. Read-only."""
    try:
        store = _clone_store(agent_id, org_id)
        events = store.get_run_events(run_id, limit=50)
        opens = store.get_open_escalations(run_id)
        return json.dumps({
            "run_id": run_id,
            "open_escalations": opens,
            "events": events,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_receipt(run_id: int, agent_id: str = "", org_id: str = "") -> str:
    """The autonomy receipt for a run: every decision, who decided (clone vs you vs
    gate), the confidence, the rationale — and the headline autonomy rate. The proof
    the loop ran AS you. Read-only."""
    try:
        from sentigent.operator.receipt import build_receipt
        store = _clone_store(agent_id, org_id)
        return json.dumps(build_receipt(store, [run_id]), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_answer(escalation_id: int, decision: str,
                    agent_id: str = "", org_id: str = "") -> str:
    """Answer an open escalation (the operator paused on it). decision is your call,
    e.g. approve | skip | takeover. Records it so the run can resume."""
    try:
        store = _clone_store(agent_id, org_id)
        store.answer_escalation(escalation_id, decision.strip())
        # Write-back: turn this answer into a precedent (+ calibrate the clone) so the
        # same class of blocker is clone-resolved next time. Autonomy compounds.
        try:
            learned = store.learn_from_escalation_answer(escalation_id, decision.strip())
        except Exception:
            learned = {"learned": False}
        return json.dumps({"escalation_id": escalation_id, "decision": decision.strip(),
                           "learned": learned,
                           "message": "recorded + learned. Call operator_resume(run_id) to "
                                      "continue the plan from where it paused."})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def operator_kill(run_id: int = 0, agent_id: str = "", org_id: str = "") -> str:
    """Instant stop. Trips the kill switch — global if run_id is 0, else that run.
    The operator checks this between every step."""
    try:
        from sentigent.operator.safety import KillSwitch

        ks = KillSwitch()
        ks.trip(str(run_id) if run_id else None)
        scope = f"run {run_id}" if run_id else "ALL runs (global)"
        return json.dumps({"killed": scope, "message": "kill switch tripped. Clear it before the next run."})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# loop_* — the DURABLE cross-session dark-factory loop (loop_driver). Unlike
# operator_loop (one in-process run to DoD), these persist the next step to disk
# so a FRESH `claude -p`/session resumes the plan after the session ends or the
# process dies. Each step carries its own done-criteria; progress is reported as
# FAP (Faithful Autonomous Progress), including a FAP-over-time trend.
# ─────────────────────────────────────────────────────────────────────────────

# MCP input is UNTRUSTED. Free-form shell gates (verify_cmd / per-step ':: cmd') would
# be a command-injection / RCE vector reachable by any MCP client, so they are refused
# by default. A human who wants shell gates can opt in with SENTIGENT_LOOP_MCP_ALLOW_SHELL=1
# (and should pair it with execute via the CLI, where they typed the command themselves).
_MCP_ALLOW_SHELL = os.environ.get("SENTIGENT_LOOP_MCP_ALLOW_SHELL", "0") == "1"


def _parse_loop_steps(steps: str, allow_shell: bool = False) -> list:
    """Steps come as text. Accept a JSON array, OR newline-separated lines where each
    line is 'do this' or 'do this :: verify_command' (the per-step gate). When
    allow_shell is False (the MCP default), per-step ':: verify' gates are DROPPED —
    the shell string is never executed from untrusted MCP input."""
    steps = (steps or "").strip()
    if not steps:
        return []
    if steps.startswith("["):
        try:
            parsed = json.loads(steps)
            if not allow_shell:
                parsed = [{"text": s.get("text", ""), } if isinstance(s, dict) else s
                          for s in parsed]
            return parsed
        except Exception:
            pass
    out = []
    for line in steps.splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if not line:
            continue
        if " :: " in line and allow_shell:
            text, _, verify = line.partition(" :: ")
            out.append({"text": text.strip(), "verify": verify.strip()})
        elif " :: " in line:
            out.append(line.partition(" :: ")[0].strip())   # drop the shell gate
        else:
            out.append(line)
    return out


def _safe_loop_cwd(cwd: str) -> str:
    """The loop's cwd becomes the working dir for `claude -p` and anchor reads, so an
    arbitrary path from MCP is an RCE vector. Default to the server's cwd; allow other
    paths only if they sit under a configured root (SENTIGENT_LOOP_ALLOWED_ROOTS,
    colon-separated). Raises ValueError otherwise."""
    base = os.getcwd()
    if not cwd or os.path.abspath(cwd) == os.path.abspath(base):
        return base
    target = os.path.abspath(cwd)
    roots = [r for r in os.environ.get("SENTIGENT_LOOP_ALLOWED_ROOTS", "").split(":") if r]
    for r in roots:
        r = os.path.abspath(r)
        if target == r or target.startswith(r + os.sep):
            return target
    raise ValueError(
        "cwd not allowed — set SENTIGENT_LOOP_ALLOWED_ROOTS to permit paths outside the "
        "server's working directory")


# execute=True over MCP runs real `claude -p` from an attacker-influenced plan/cwd —
# that's RCE-equivalent. Refuse it unless a human opted in out-of-band.
_MCP_ALLOW_EXECUTE = os.environ.get("SENTIGENT_LOOP_MCP_ALLOW_EXECUTE", "0") == "1"


def _mcp_execute_guard(execute: bool) -> str:
    if execute and not _MCP_ALLOW_EXECUTE:
        return json.dumps({"error": "execute=True is disabled over MCP. Set "
                           "SENTIGENT_LOOP_MCP_ALLOW_EXECUTE=1 to allow real laps from "
                           "MCP, or drive the loop from the CLI. Dry-run (execute=False) "
                           "works without it."})
    return ""


@_tool()
def loop_start(goal: str, steps: str = "", cwd: str = "",
               anchor_files: str = "", guardrails: bool = False,
               max_attempts: int = 3) -> str:
    """Seed a DURABLE cross-session loop (the dark factory). Stores the plan + the
    next step to disk so a fresh session can resume it after this one ends.

    steps: a JSON array, OR newline-separated lines. (Per-step shell gates 'text :: cmd'
    and free-form verify commands are IGNORED over MCP for safety — set
    SENTIGENT_LOOP_MCP_ALLOW_SHELL=1, or use the CLI, to attach real gates.) cwd must be
    the server's working dir or under SENTIGENT_LOOP_ALLOWED_ROOTS. anchor_files:
    comma-separated RELATIVE paths under cwd (VISION.md, CLAUDE.md…) re-injected each lap.
    guardrails=True enforces org guardrail packs per lap. Returns the loop_id + status."""
    try:
        from sentigent.operator import loop_driver as L
        safe_cwd = _safe_loop_cwd(cwd)
        parsed = _parse_loop_steps(steps, allow_shell=_MCP_ALLOW_SHELL) or [goal]
        # anchors: relative-only, no traversal (driver re-checks, but reject early too)
        anchors = [a.strip() for a in anchor_files.split(",")
                   if a.strip() and not os.path.isabs(a.strip()) and ".." not in a.strip().split("/")]
        st = L.start(goal, parsed, cwd=safe_cwd, verify_cmd="",
                     anchor_files=anchors, max_attempts=max_attempts, guardrails=guardrails)
        note = "" if _MCP_ALLOW_SHELL else " (shell gates ignored — set SENTIGENT_LOOP_MCP_ALLOW_SHELL=1 to enable)"
        return L.status_line(st) + "\n\n" + json.dumps(
            {"loop_id": st["loop_id"], "steps": len(st["steps"]),
             "next": f"loop_drive(loop_id) to dry-run{note}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def loop_drive(loop_id: str, execute: bool = False, max_steps: int = 50,
               timeout: int = 1800) -> str:
    """Drive a loop forward, lap after lap, until done / blocked / max / budget.
    DRY-RUN by default (execute=False) — no `claude -p`. execute=True runs real laps and
    is REFUSED over MCP unless SENTIGENT_LOOP_MCP_ALLOW_EXECUTE=1 (RCE safety). Returns
    the status line + FAP metrics. Safe to call again later (even from a new session)."""
    try:
        from sentigent.operator import loop_driver as L
        blocked = _mcp_execute_guard(execute)
        if blocked:
            return blocked
        st = L.drive(loop_id, execute=execute, max_steps=max_steps, timeout=timeout)
        return L.status_line(st) + "\n\n" + json.dumps(L.metrics(st))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def loop_resume(loop_id: str, execute: bool = False, max_steps: int = 50,
                timeout: int = 1800) -> str:
    """Resume a loop after a session ended, a crash, or a human answer to a blocker.
    Reads the durable state from disk and continues from the stored next step. execute=True
    is REFUSED over MCP unless SENTIGENT_LOOP_MCP_ALLOW_EXECUTE=1. Same return shape as
    loop_drive."""
    try:
        from sentigent.operator import loop_driver as L
        blocked = _mcp_execute_guard(execute)
        if blocked:
            return blocked
        st = L.resume(loop_id, execute=execute, max_steps=max_steps, timeout=timeout)
        return L.status_line(st) + "\n\n" + json.dumps(L.metrics(st))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def loop_answer(loop_id: str, decision: str) -> str:
    """Answer a loop's open blocker AS the human (approve / skip / takeover). Records the
    precedent AND scores the clone's attempt (calibration) so the loop's push-vs-ask
    judgment learns from this real outcome — then reopens the step and sets the loop back
    to running so loop_drive/loop_resume continues. Returns what was learned + new status."""
    try:
        from sentigent.operator import loop_driver as L
        return json.dumps(L.answer(loop_id, decision))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def loop_status(loop_id: str) -> str:
    """Where is this loop? Returns the status line (goal · next step · FAP) + metrics
    for one loop, read straight from its persisted state."""
    try:
        from sentigent.operator import loop_driver as L
        st = L.load(loop_id)
        return L.status_line(st) + "\n\n" + json.dumps(L.metrics(st))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@_tool()
def loop_receipt() -> str:
    """The dark-factory scoreboard across ALL loops: per-run FAP/distance/fidelity,
    means, and the FAP-over-time trend (is the system getting smarter?). Real numbers
    only — each row is computed from that loop's own persisted state."""
    try:
        import io
        from contextlib import redirect_stdout
        from sentigent.operator import loop_driver as L
        buf = io.StringIO()
        with redirect_stdout(buf):
            L.print_receipt()
        return buf.getvalue() + "\n" + json.dumps(L.receipt()["aggregate"])
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
