"""CLI interface for Sentigent — stats, signals, and judgment score.

Usage:
    sentigent init           — Interactive setup for Claude Code integration
    sentigent doctor         — Health check verifying all components
    sentigent reset          — Remove Sentigent from Claude Code config
    sentigent dashboard      — Rich terminal dashboard with analytics
    sentigent web            — Launch web dashboard (http://localhost:7777)
    sentigent stats          — Show agent statistics
    sentigent score          — Show judgment score over time
    sentigent audit          — Human-readable audit of decisions and observations
    sentigent profiles       — List available domain profiles
    sentigent version        — Show version
"""

from __future__ import annotations

import argparse
import sys

from sentigent import __version__
from sentigent.profiles.registry import list_profiles


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="sentigent",
        description="Sentigent — The judgment layer that learns",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sentigent {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # init command
    subparsers.add_parser("init", help="Interactive setup for Claude Code integration")

    # doctor command
    subparsers.add_parser("doctor", help="Health check verifying all components")

    # reset command
    subparsers.add_parser("reset", help="Remove Sentigent from Claude Code config (keeps DB)")

    # dashboard command
    subparsers.add_parser("dashboard", help="Rich terminal dashboard with analytics")

    # web command
    web_parser = subparsers.add_parser("web", help="Launch web dashboard")
    web_parser.add_argument("--port", type=int, default=7777, help="Port (default: 7777)")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show agent statistics")
    stats_parser.add_argument("--agent-id", default="default_agent", help="Agent ID")
    stats_parser.add_argument("--db-path", default=None, help="Path to memory database")

    # score command
    score_parser = subparsers.add_parser("score", help="Show judgment score")
    score_parser.add_argument("--agent-id", default="default_agent", help="Agent ID")
    score_parser.add_argument("--db-path", default=None, help="Path to memory database")

    # export command
    export_parser = subparsers.add_parser("export", help="Export audit trail (CSV or JSON)")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv",
                              help="Output format (default: csv)")
    export_parser.add_argument("--days", type=int, default=30,
                              help="Export last N days (default: 30)")
    export_parser.add_argument("--output", "-o", default=None,
                              help="Output file (default: stdout)")

    # coach command
    coach_parser = subparsers.add_parser(
        "coach",
        help="AI-powered interaction coach — get suggestions to improve your agent workflows",
    )
    coach_parser.add_argument("--agent-id", default="", help="Agent ID (default: config default_agent)")
    coach_parser.add_argument("--days", type=int, default=7, help="Look-back window in days (default: 7)")
    coach_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")

    # audit command
    audit_parser = subparsers.add_parser(
        "audit",
        help="Human-readable audit of decisions, failures, and learned patterns",
    )
    audit_parser.add_argument("--agent-id", default="", help="Agent ID (default: config default_agent)")
    audit_parser.add_argument("--days", type=int, default=7, help="Look-back window in days (default: 7)")
    audit_parser.add_argument("--failures", action="store_true", help="Show only failures")
    audit_parser.add_argument("--patterns", action="store_true", help="Show learned patterns/rules")
    audit_parser.add_argument("--tools", action="store_true", help="Show failure rate by tool")

    # prove command
    prove_parser = subparsers.add_parser(
        "prove",
        help="Proof-of-value report — show evidence that Sentigent is working",
    )
    prove_parser.add_argument("--agent-id", default="", help="Agent ID (default: config default_agent)")
    prove_parser.add_argument("--days", type=int, default=90, help="Look-back window in days (default: 90)")
    prove_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")

    # policy command
    policy_parser = subparsers.add_parser(
        "policy",
        help="Manage org-wide policies (list, add, disable)",
    )
    policy_parser.add_argument("action", choices=["list", "add", "disable"], nargs="?", default="list")
    policy_parser.add_argument("--name", help="Policy name")
    policy_parser.add_argument("--tool", default="*", help="Tool to match (Bash, Write, Edit, *)")
    policy_parser.add_argument("--pattern", default="", help="Regex pattern on task/command")
    policy_parser.add_argument("--enforce", default="slow_down",
                               choices=["block", "escalate", "slow_down", "enrich"],
                               help="Enforcement action")
    policy_parser.add_argument("--reason", default="", help="Human-readable reason")
    policy_parser.add_argument("--severity", default="medium",
                               choices=["low", "medium", "high", "critical"])

    # profiles command
    subparsers.add_parser("profiles", help="List available domain profiles")

    # profile command (org-level profile management)
    profile_parser = subparsers.add_parser(
        "profile",
        help="Manage org-level agent profiles (product_manager, security_engineer, ...)",
    )
    profile_parser.add_argument(
        "action",
        choices=["get", "list", "assign", "builtin"],
        nargs="?",
        default="get",
        help="Action: get (current), list (available), assign (set profile), builtin (templates)",
    )
    profile_parser.add_argument("--agent-id", default="", help="Agent ID")
    profile_parser.add_argument("--name", default="", help="Profile name (required for assign)")

    # prompt-health command
    prompt_health_parser = subparsers.add_parser(
        "prompt-health",
        help="Analyze prompt quality — see how your instructions affect agent outcomes",
    )
    prompt_health_parser.add_argument("--agent-id", default="", help="Agent ID (default: config default_agent)")
    prompt_health_parser.add_argument("--days", type=int, default=30, help="Look-back days")
    prompt_health_parser.add_argument("--json", action="store_true", dest="as_json")

    # collective command (Layer 3)
    collective_parser = subparsers.add_parser(
        "collective",
        help="Layer 3 collective intelligence — cross-org anonymized pattern sharing",
    )
    collective_parser.add_argument(
        "action",
        choices=["status", "opt-in", "opt-out", "pull", "contribute"],
        nargs="?",
        default="status",
        help="Action: status, opt-in, opt-out, pull, contribute",
    )
    collective_parser.add_argument("--profile", default="default", help="Profile name")
    collective_parser.add_argument("--tags", nargs="*", help="Industry tags (e.g. fintech healthcare)")
    collective_parser.add_argument("--org-id", default="hussi", help="Org ID")

    # report command
    report_parser = subparsers.add_parser(
        "report",
        help="Show savings report and monthly bill estimate",
    )
    report_parser.add_argument("--month", default="", help="YYYY-MM (defaults to current month)")
    report_parser.add_argument("--agent-id", default="", help="Agent ID")
    report_parser.add_argument("--json", action="store_true", dest="as_json")

    practices_parser = subparsers.add_parser(
        "practices",
        help="Your enforced best-practice playbook (list/add/enforce/toggle)",
    )
    practices_parser.add_argument(
        "action", nargs="?", default="list",
        choices=["list", "add", "enforce", "toggle"],
    )
    practices_parser.add_argument(
        "rest", nargs="*",
        help='add "<text>" | enforce <id> <off|warn|block> | toggle <id> <on|off>',
    )
    practices_parser.add_argument("--cadence", default="commit",
                                  help="always|commit|milestone|deploy|pr (for add)")
    practices_parser.add_argument("--agent-id", default="", help="Agent ID")
    practices_parser.add_argument("--db-path", default=None, dest="db_path")
    practices_parser.add_argument("--json", action="store_true", dest="as_json",
                                  help="Output practices as compact JSON")

    args = parser.parse_args()

    if args.command == "init":
        from sentigent.onboarding import cmd_init
        cmd_init()
    elif args.command == "doctor":
        from sentigent.onboarding import cmd_doctor
        cmd_doctor()
    elif args.command == "reset":
        from sentigent.onboarding import cmd_reset
        cmd_reset()
    elif args.command == "dashboard":
        from sentigent.dashboard import cmd_dashboard
        cmd_dashboard()
    elif args.command == "web":
        from sentigent.dashboard import cmd_web
        cmd_web(port=args.port)
    elif args.command == "coach":
        _cmd_coach(agent_id=args.agent_id, days=args.days, as_json=args.as_json)
    elif args.command == "audit":
        _cmd_audit(
            agent_id=args.agent_id,
            days=args.days,
            only_failures=args.failures,
            only_patterns=args.patterns,
            by_tools=args.tools,
        )
    elif args.command == "export":
        _cmd_export(args.format, args.days, args.output)
    elif args.command == "prove":
        _cmd_prove(agent_id=args.agent_id, days=args.days, as_json=args.as_json)
    elif args.command == "policy":
        _cmd_policy(
            action=args.action or "list",
            name=getattr(args, "name", None),
            tool=getattr(args, "tool", "*"),
            pattern=getattr(args, "pattern", ""),
            enforce=getattr(args, "enforce", "slow_down"),
            reason=getattr(args, "reason", ""),
            severity=getattr(args, "severity", "medium"),
        )
    elif args.command == "profiles":
        _cmd_profiles()
    elif args.command == "profile":
        _cmd_profile(
            action=getattr(args, "action", "get"),
            agent_id=getattr(args, "agent_id", ""),
            profile_name=getattr(args, "name", ""),
        )
    elif args.command == "prompt-health":
        _cmd_prompt_health(
            agent_id=args.agent_id,
            days=args.days,
            as_json=args.as_json,
        )
    elif args.command == "collective":
        _cmd_collective(
            action=(args.action or "status").replace("-", "_"),
            profile_name=args.profile,
            org_id=args.org_id,
            tags=args.tags,
        )
    elif args.command == "stats":
        _cmd_stats(args.agent_id, args.db_path)
    elif args.command == "score":
        _cmd_score(args.agent_id, args.db_path)
    elif args.command == "report":
        _cmd_report(
            month=args.month,
            agent_id=args.agent_id,
            as_json=args.as_json,
        )
    elif args.command == "practices":
        _cmd_practices(
            action=args.action,
            rest=args.rest,
            cadence=args.cadence,
            agent_id=args.agent_id,
            db_path=args.db_path,
            as_json=args.as_json,
        )
    else:
        parser.print_help()


def _cmd_coach(agent_id: str, days: int, as_json: bool) -> None:
    """Run the AI interaction coach and print suggestions."""
    from sentigent.config import get_config
    from sentigent.core.coach import InteractionCoach
    import json as _json

    agent_id = agent_id or get_config().agent_id
    print(f"\nAnalyzing {days} days of interactions for agent '{agent_id}'...")
    print("(Requires ANTHROPIC_API_KEY for AI suggestions — falls back to rule-based)\n")

    coach = InteractionCoach(agent_id=agent_id)
    report = coach.analyze(lookback_days=days)

    if as_json:
        print(_json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_text())


def _cmd_audit(
    agent_id: str,
    days: int,
    only_failures: bool,
    only_patterns: bool,
    by_tools: bool,
) -> None:
    """Human-readable audit: what the agent decided, what failed, what was learned."""
    import json
    import sqlite3
    from collections import defaultdict
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from sentigent.config import get_config

    agent_id = agent_id or get_config().agent_id
    db_path = Path.home() / ".sentigent" / f"memory_{agent_id}.db"
    if not db_path.exists():
        print(f"No database found for agent '{agent_id}' at {db_path}")
        print("Run `sentigent init` to set up Sentigent first.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # ── Section: Tool failure rates ──────────────────────────────────────────
    if by_tools or not (only_failures or only_patterns):
        print(f"\n{'='*60}")
        print(f"  TOOL OBSERVATION REPORT — last {days} days — agent: {agent_id}")
        print(f"{'='*60}\n")

        rows = conn.execute(
            "SELECT context, outcome FROM episodes WHERE timestamp >= ? AND outcome IS NOT NULL",
            (cutoff,),
        ).fetchall()

        tool_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in rows:
            try:
                ctx = json.loads(r["context"]) if r["context"] else {}
            except Exception:
                ctx = {}
            tool = ctx.get("tool_name", "unknown")
            tool_stats[tool][r["outcome"]] += 1

        print("  Tool              | Correct | Incorrect | Neutral | Fail Rate")
        print("  " + "-" * 58)
        for tool, outcomes in sorted(tool_stats.items()):
            correct = outcomes.get("correct", 0)
            incorrect = outcomes.get("incorrect", 0)
            neutral = outcomes.get("neutral", 0)
            total = correct + incorrect + neutral
            fail_rate = incorrect / total if total > 0 else 0
            flag = " ⚠" if fail_rate >= 0.1 else ""
            print(
                f"  {tool:<17s} | {correct:>7} | {incorrect:>9} | {neutral:>7} | "
                f"{fail_rate:>6.1%}{flag}"
            )
        print()

    # ── Section: Recent failures ─────────────────────────────────────────────
    if only_failures or not (only_patterns or by_tools):
        print(f"\n  RECENT FAILURES (last {days} days)\n  {'─'*56}")
        rows = conn.execute(
            """SELECT timestamp, task, outcome_feedback, signals, decision
               FROM episodes
               WHERE outcome = 'incorrect' AND timestamp >= ?
               ORDER BY timestamp DESC LIMIT 30""",
            (cutoff,),
        ).fetchall()

        if not rows:
            print("  No failures recorded. Either nothing failed, or outcomes aren't being captured.")
            print("  Tip: Check that PostToolUse hooks are active with `sentigent doctor`\n")
        else:
            for r in rows:
                ts = str(r["timestamp"])[:16].replace("T", " ")
                task = str(r["task"])[:65]
                feedback = str(r["outcome_feedback"] or "")[:80]
                print(f"\n  [{ts}] {task}")
                print(f"  Feedback: {feedback}")

        print()

    # ── Section: Learned patterns / procedural rules ─────────────────────────
    if only_patterns or not (only_failures or by_tools):
        print(f"  LEARNED PATTERNS (procedural rules)\n  {'─'*56}")
        rows = conn.execute(
            "SELECT pattern_name, learned_action, success_rate, sample_size, condition FROM procedural_rules ORDER BY sample_size DESC"
        ).fetchall()

        if not rows:
            print("  No patterns learned yet.")
            print(f"  Patterns form after {30} consistent outcomes. Keep using the agent.\n")
        else:
            for r in rows:
                advisory = ""
                try:
                    cond = json.loads(r["condition"]) if r["condition"] else {}
                    if isinstance(cond, str):
                        cond = json.loads(cond)
                    advisory = cond.get("advisory", "")
                except Exception:
                    pass
                print(f"\n  Pattern: {r['pattern_name']}")
                print(f"  Action:  {r['learned_action']}  |  Success: {r['success_rate']:.1%}  |  n={r['sample_size']}")
                if advisory:
                    print(f"  Note:    {advisory}")
        print()

    # ── Section: Bash-specific failures (from /tmp tracker) ──────────────────
    bash_fail_file = Path("/tmp/sentigent_bash_failures.json")
    if bash_fail_file.exists() and not only_patterns:
        try:
            failures = json.loads(bash_fail_file.read_text())
            if failures:
                from collections import Counter
                prefixes = [f.get("command", "").split()[0] for f in failures if f.get("command")]
                top = Counter(prefixes).most_common(5)
                print(f"  BASH FAILURE TRACKER (since last hook restart)\n  {'─'*56}")
                for prefix, count in top:
                    last = next((f for f in reversed(failures) if f.get("command", "").startswith(prefix)), {})
                    suggested = last.get("suggested_tool", "mcp__desktop-commander")
                    print(f"  {prefix:<20s}  {count:>3} failures  →  try: {suggested}")
                print()
        except Exception:
            pass

    conn.close()


def _cmd_profiles() -> None:
    """List available domain profiles."""
    profiles = list_profiles()
    print("Available domain profiles:")
    print()
    for name in profiles:
        print(f"  - {name}")
    print()
    print("Usage: Sentigent(profile=\"financial_ops\")")


def _cmd_stats(agent_id: str, db_path: str | None) -> None:
    """Show agent statistics."""
    from sentigent.memory.store import MemoryStore

    store = MemoryStore(agent_id=agent_id, org_id="cli", db_path=db_path)
    episode_count = store.get_episode_count()
    outcome_stats = store.get_outcome_stats()
    baselines = store.get_baselines()

    print(f"Agent: {agent_id}")
    print(f"Total episodes: {episode_count}")
    print()

    if outcome_stats:
        print("Outcomes:")
        for outcome, count in sorted(outcome_stats.items()):
            print(f"  {outcome}: {count}")
        total = sum(outcome_stats.values())
        correct = outcome_stats.get("correct", 0)
        if total > 0:
            print(f"  Judgment score: {correct / total:.1%}")
    else:
        print("No outcomes recorded yet.")

    print()
    if baselines:
        print("Learned baselines:")
        for name, stats in sorted(baselines.items()):
            print(f"  {name}: median={stats.median:.1f}, std={stats.std:.1f} (n={stats.sample_size})")
    else:
        print("No learned baselines yet (using profile defaults).")


def _cmd_score(agent_id: str, db_path: str | None) -> None:
    """Show judgment score."""
    from sentigent.memory.store import MemoryStore

    store = MemoryStore(agent_id=agent_id, org_id="cli", db_path=db_path)
    outcome_stats = store.get_outcome_stats()

    if not outcome_stats:
        print("No outcomes recorded yet. Record outcomes to see your judgment score.")
        return

    total = sum(outcome_stats.values())
    correct = outcome_stats.get("correct", 0)
    score = correct / total if total > 0 else 0

    # ASCII bar chart
    bar_width = 40
    filled = int(score * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    print(f"Judgment Score: {score:.1%}")
    print(f"  [{bar}]")
    print()
    print(f"  Correct:   {correct}")
    print(f"  Incorrect: {outcome_stats.get('incorrect', 0)}")
    print(f"  Neutral:   {outcome_stats.get('neutral', 0)}")
    print(f"  Total:     {total}")

    # Recent-window, graded-only judgment metric (read-only; default 7 days).
    recent = store.get_recent_graded_accuracy(7)
    window = recent["window_days"]
    graded_total = recent["graded_total"]
    accuracy = recent["accuracy"]
    print()
    if accuracy is None:
        print(f"Recent ({window}d): no graded decisions in window")
    else:
        print(f"Recent ({window}d): {accuracy:.1%}")
        print(
            f"  Graded:    {graded_total} "
            f"({recent['correct']} correct / {recent['incorrect']} incorrect)"
        )


def _cmd_practices(
    action: str,
    rest: list[str],
    cadence: str,
    agent_id: str,
    db_path: str | None,
    as_json: bool = False,
) -> None:
    """Manage the enforced best-practice playbook from the CLI.

    Mirrors the sentigent_practices MCP tool: list / add / enforce / toggle.
    Enforcement level (off|warn|block) is the dial for how hard the practice
    gate holds you to each practice at its cadence.

    Resolves agent/org the same way every other CLI command does (explicit
    flag, else the config default) so a fresh ``sentigent practices add``
    lands in the *same* database ``init``/``doctor``/``score`` already point
    at — previously this hardcoded ``agent_id=""``/``org_id="cli"``, silently
    writing to a sibling ``memory_.db`` that nothing else ever read.
    """
    import os

    from sentigent.config import get_config
    from sentigent.memory.store import MemoryStore

    cfg = get_config()
    aid = agent_id or cfg.agent_id
    org_id = os.environ.get("SENTIGENT_ORG_ID") or cfg.org_id
    store = MemoryStore(agent_id=aid, org_id=org_id, db_path=db_path)

    if action == "add":
        text = " ".join(rest).strip()
        if not text:
            print('usage: sentigent practices add "<practice text>" [--cadence commit]')
            return
        pid = store.add_practice(text, domain="global", cadence=cadence)
        print(f"added #{pid}  (cadence={cadence}, enforcement=warn):  {text}")
        return

    if action == "enforce":
        if len(rest) < 2 or not rest[0].isdigit():
            print("usage: sentigent practices enforce <id> <off|warn|block>")
            return
        try:
            store.set_practice_enforcement(int(rest[0]), rest[1])
        except ValueError as exc:
            print(f"error: {exc}")
            return
        print(f"practice #{rest[0]} → enforcement={rest[1].strip().lower()}")
        return

    if action == "toggle":
        if len(rest) < 2 or not rest[0].isdigit():
            print("usage: sentigent practices toggle <id> <on|off>")
            return
        on = rest[1].strip().lower() in ("on", "true", "1", "yes")
        store.set_practice_active(int(rest[0]), on)
        print(f"practice #{rest[0]} → active={on}")
        return

    # list
    rows = store.get_practices(active_only=False)
    if as_json:
        from pydantic import BaseModel

        class PracticeJson(BaseModel):
            name: str
            enabled: bool
            rules: list[str]
            last_checked_at: float | None
            violations_count: int

        print("[" + ",".join(
            PracticeJson(
                name=r["text"],
                enabled=bool(r["active"]),
                rules=[r["text"]],
                last_checked_at=r.get("last_checked_at"),
                violations_count=int(r.get("times_skipped") or 0),
            ).model_dump_json()
            for r in rows
        ) + "]")
        return

    if not rows:
        print('No practices yet. Add one:')
        print('  sentigent practices add "Run the tests before committing"')
        return
    print(f"{'id':>3}  {'enforce':<7} {'cadence':<9} {'foll/skip':<9} practice")
    print("  " + "-" * 66)
    for r in rows:
        state = "" if r["active"] else "  (inactive)"
        fs = f"{r['times_followed']}/{r['times_skipped']}"
        print(f"{r['id']:>3}  {r.get('enforcement', 'warn'):<7} "
              f"{r['cadence']:<9} {fs:<9} {r['text']}{state}")


def _cmd_export(fmt: str, days: int, output_path: str | None) -> None:
    """Export audit trail as CSV or JSON.

    Exports: timestamp, tool, action, decision, confidence, outcome, policy_violations
    """
    import csv
    import io
    import json
    import sqlite3
    from datetime import datetime, timedelta
    from pathlib import Path

    from sentigent.config import get_config

    config = get_config()
    db_path = config.db_path or str(Path.home() / ".sentigent" / f"memory_{config.agent_id}.db")

    if not Path(db_path).exists():
        print(f"No database found at {db_path}. Run 'sentigent init' first.", file=sys.stderr)
        sys.exit(1)

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT trace_id, timestamp, task, context, signals, decision,
               confidence_at_decision, outcome, outcome_feedback
        FROM episodes
        WHERE agent_id = ? AND timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (config.agent_id, cutoff),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"No episodes in the last {days} days.", file=sys.stderr)
        sys.exit(0)

    # Build export data
    records = []
    for row in rows:
        record = {
            "trace_id": row["trace_id"],
            "timestamp": row["timestamp"],
            "task": row["task"],
            "decision": row["decision"],
            "confidence": row["confidence_at_decision"],
            "outcome": row["outcome"] or "",
            "feedback": row["outcome_feedback"] or "",
            "signals": row["signals"],
        }
        records.append(record)

    # Format output
    if fmt == "json":
        content = json.dumps(records, indent=2, default=str)
    else:
        # CSV
        buf = io.StringIO()
        fieldnames = ["trace_id", "timestamp", "task", "decision",
                      "confidence", "outcome", "feedback", "signals"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
        content = buf.getvalue()

    # Write to file or stdout
    if output_path:
        with open(output_path, "w") as f:
            f.write(content)
        print(f"Exported {len(records)} episodes to {output_path}", file=sys.stderr)
    else:
        print(content)


def _cmd_prove(agent_id: str, days: int, as_json: bool) -> None:
    """Proof-of-value report: evidence that Sentigent is working."""
    import json as _json
    import os

    # Load .env for Supabase
    from pathlib import Path as _Path
    env_file = _Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

    from sentigent.config import get_config
    cfg = get_config()
    agent_id = agent_id or cfg.agent_id
    org_id = cfg.org_id or os.environ.get("SENTIGENT_ORG_ID", "")

    from sentigent.core.prove import ProofEngine
    engine = ProofEngine(agent_id=agent_id, org_id=org_id)
    report = engine.compute(days=days)

    if as_json:
        print(_json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_text())


def _cmd_policy(
    action: str,
    name: str | None,
    tool: str,
    pattern: str,
    enforce: str,
    reason: str,
    severity: str,
) -> None:
    """Manage org-wide policies."""
    import json as _json
    import os
    from pathlib import Path as _Path

    # Load .env
    env_file = _Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    org_id = os.environ.get("SENTIGENT_ORG_ID", "")

    if not url or not key:
        print("Layer 2 not configured. Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.")
        return

    try:
        from supabase import create_client
        client = create_client(url, key)
    except Exception as exc:
        print(f"Supabase connection failed: {exc}")
        return

    if action == "list":
        result = (
            client.table("org_policies")
            .select("policy_name,trigger_tool,trigger_pattern,enforce_action,severity,is_active,trigger_count")
            .eq("org_id", org_id)
            .order("severity")
            .execute()
        )
        policies = result.data or []
        if not policies:
            print(f"No policies configured for org '{org_id}'.")
            print("Run: sentigent policy add --name <name> --pattern <regex> --enforce block")
            return

        print(f"\n  Org Policies — {org_id}\n  {'─'*70}")
        print(f"  {'Name':<28} {'Tool':<8} {'Action':<10} {'Severity':<10} {'Triggers':>8}")
        print(f"  {'─'*68}")
        for p in policies:
            active = "" if p.get("is_active") else " [DISABLED]"
            print(
                f"  {p['policy_name']:<28} {p.get('trigger_tool','*'):<8} "
                f"{p.get('enforce_action',''):<10} {p.get('severity',''):<10} "
                f"{p.get('trigger_count',0):>8}{active}"
            )
        print()

    elif action == "add":
        if not name:
            print("--name is required for policy add")
            return
        try:
            client.table("org_policies").insert({
                "org_id": org_id,
                "policy_name": name,
                "trigger_tool": tool,
                "trigger_pattern": pattern,
                "enforce_action": enforce,
                "enforce_reason": reason,
                "severity": severity,
                "is_active": True,
                "created_by": os.environ.get("SENTIGENT_AGENT_ID", "cli"),
            }).execute()
            print(f"Policy '{name}' added ({enforce} on {tool} matching '{pattern}').")
        except Exception as exc:
            print(f"Failed to add policy: {exc}")

    elif action == "disable":
        if not name:
            print("--name is required for policy disable")
            return
        try:
            client.table("org_policies").update({"is_active": False}).eq(
                "org_id", org_id
            ).eq("policy_name", name).execute()
            print(f"Policy '{name}' disabled.")
        except Exception as exc:
            print(f"Failed to disable policy: {exc}")


def _cmd_profile(action: str, agent_id: str, profile_name: str) -> None:
    """Manage org-level agent profiles."""
    import json as _json
    import os

    from pathlib import Path as _Path
    env_file = _Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

    from sentigent.config import get_config
    cfg = get_config()
    aid = agent_id or cfg.agent_id
    org_id = cfg.org_id or os.environ.get("SENTIGENT_ORG_ID", "default")

    from sentigent.core.profile_intelligence import (
        get_profile_intelligence,
        ProfileIntelligence,
        BUILTIN_PROFILES,
    )
    pi = get_profile_intelligence(org_id=org_id, agent_id=aid)

    if action == "get":
        report = pi.get_profile_report()
        print(f"\nAgent Profile: {aid}")
        print(f"  Active profile : {report.active_profile}")
        print(f"  Role           : {report.role}")
        print(f"  Description    : {report.description[:80]}")
        if report.value_weights:
            print("  Value weights  :")
            for k, v in sorted(report.value_weights.items(), key=lambda x: -x[1]):
                bar = "▓" * int(v * 10) + "░" * (10 - int(v * 10))
                print(f"    {k:<25} [{bar}] {v:.1f}")
        if report.ai_context_hint:
            print(f"\n  Coach context  : {report.ai_context_hint[:100]}")
        print(f"\n  Policy templates: {report.policy_templates_count}")
        print(f"  Available profiles: {', '.join(report.available_profiles)}\n")

    elif action == "list":
        report = pi.get_profile_report()
        print(f"\nAvailable profiles (org={org_id}):")
        for p in report.available_profiles:
            active_marker = " ← active" if p == report.active_profile else ""
            builtin_info = BUILTIN_PROFILES.get(p, {})
            desc = (builtin_info.get("description", "") or "")[:70]
            print(f"  {p:<25} {desc}{active_marker}")
        print()

    elif action == "assign":
        if not profile_name:
            print("Error: --name <profile_name> required for assign", file=sys.stderr)
            sys.exit(1)
        available = list(BUILTIN_PROFILES.keys())
        saved = pi.assign_profile(profile_name)
        print(f"\nAssigned profile '{profile_name}' to agent '{aid}'")
        if saved:
            print("  ✓ Persisted to Supabase")
        else:
            print("  (Local only — Supabase not configured or 003 migration not run)")
        print(f"\nNote: The {profile_name} profile includes:")
        tmpl = BUILTIN_PROFILES.get(profile_name, {})
        if tmpl:
            for k, v in tmpl.get("value_weights", {}).items():
                print(f"  {k}: {v:.1f}")
        print()

    elif action == "builtin":
        print("\nBuilt-in profile templates:")
        for p in ProfileIntelligence.list_builtin_profiles():
            print(f"\n  {p['name']}")
            print(f"  {p['description'][:120]}")
        print()


def _cmd_prompt_health(agent_id: str, days: int, as_json: bool) -> None:
    """Analyze prompt quality patterns and suggest improvements."""
    import json as _json

    from sentigent.config import get_config
    from sentigent.core.prompt_observer import PromptObserver

    agent_id = agent_id or get_config().agent_id
    observer = PromptObserver(agent_id=agent_id)
    report = observer.analyze(lookback_days=days)

    if as_json:
        print(_json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_text())


def _cmd_collective(
    action: str,
    profile_name: str,
    org_id: str,
    tags: list[str] | None,
) -> None:
    """Manage Layer 3 cross-org collective intelligence."""
    import os as _os

    from sentigent.sync.manager import SyncManager

    agent_id = _os.environ.get("SENTIGENT_AGENT_ID", "default_agent")
    mgr = SyncManager(org_id=org_id, agent_id=agent_id)

    if action == "status":
        status = mgr.get_layer3_status()
        print("\n=== Layer 3 Collective Intelligence ===")
        print(f"  Pool size:          {status.get('pool_size', 0)} patterns")
        print(f"  Multi-org patterns: {status.get('multi_org_patterns', 0)}")
        print(f"  Avg success rate:   {status.get('pool_avg_success_rate', 0):.1%}")
        opted = status.get("opted_in_profiles", [])
        print(f"  Opted-in profiles:  {', '.join(opted) or 'none'}")
        print()

    elif action in ("opt_in", "opt_out"):
        opted = action == "opt_in"
        ok = mgr.set_layer3_opt_in(profile_name, opted)
        if ok:
            print(
                f"\nLayer 3: org {('opted IN to' if opted else 'opted OUT of')} "
                f"contributing patterns for profile='{profile_name}'"
            )
        else:
            print("\nFailed to update opt-in status (Supabase not configured?)", file=sys.stderr)

    elif action == "pull":
        patterns = mgr.pull_layer3_patterns(industry_tags=tags)
        if not patterns:
            print("\nLayer 3: pool is empty (no patterns contributed yet)")
            return
        print(f"\nLayer 3 shared patterns ({len(patterns)} total):")
        for p in patterns[:30]:
            print(
                f"  {p['pattern_name']:<50s} → {p['learned_action']:<12s}  "
                f"rate={p['success_rate']:.0%}  orgs={p['contributing_org_count']}"
            )
        print()

    elif action == "contribute":
        import os as _os2
        from sentigent.learning.pattern_miner import PatternMiner
        db_path = _os2.path.expanduser("~/.sentigent/memory.db")
        miner = PatternMiner(db_path=db_path)
        patterns = miner.get_patterns(min_success_rate=0.85, min_samples=5)
        if not patterns:
            print("\nNo qualifying patterns to contribute (need success_rate≥0.85 and 5+ samples)")
            return
        result = mgr.contribute_to_layer3(
            [
                {
                    "pattern_name": p.pattern_name,
                    "learned_action": p.learned_action,
                    "success_rate": p.success_rate,
                    "sample_size": p.sample_size,
                }
                for p in patterns
            ],
            profile_name=profile_name,
            industry_tags=tags,
        )
        if not result["opted_in"]:
            print(
                f"\nNot opted in for profile='{profile_name}'. "
                f"Run: sentigent collective opt-in --profile {profile_name}"
            )
        else:
            print(
                f"\nLayer 3 contribution: {result['contributed']} patterns shared, "
                f"{result['skipped']} skipped"
            )


def _cmd_report(month: str, agent_id: str, as_json: bool) -> None:
    """Show savings report and monthly bill estimate from local cost events."""
    import datetime
    import json as _json
    import os
    from sentigent.billing.calculator import compute_monthly_bill, format_bill

    now = datetime.datetime.now()
    if month:
        try:
            dt = datetime.datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
        except ValueError:
            print(f"Invalid --month format '{month}'. Use YYYY-MM.")
            sys.exit(1)
    else:
        year, mon = now.year, now.month

    resolved_agent = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "default")

    # Load cost events from local DB if available
    events: list[dict] = []
    try:
        from sentigent.memory.store import MemoryStore
        store = MemoryStore(agent_id=resolved_agent, org_id="default")
        events = store.get_cost_events_for_month(year=year, month=mon)
    except Exception:
        pass

    period = compute_monthly_bill(
        events=events,
        year=year,
        month=mon,
        agent_id=resolved_agent,
        org_id="default",
    )

    if as_json:
        print(_json.dumps({
            "year": period.year,
            "month": period.month,
            "agent_id": period.agent_id,
            "total_cost_usd": period.total_cost_usd,
            "total_baseline_usd": period.total_baseline_usd,
            "total_savings_usd": period.total_savings_usd,
            "savings_pct": period.savings_pct,
            "success_fee_usd": period.success_fee_usd,
            "platform_fee_usd": period.platform_fee_usd,
            "total_due_usd": period.total_due_usd,
            "event_count": period.event_count,
            "total_tokens": period.total_tokens,
        }, indent=2))
    else:
        print()
        print(format_bill(period))
        if not events:
            print("\n  (No cost events recorded yet — events accumulate as you use Sentigent)")
        print()


if __name__ == "__main__":
    main()
