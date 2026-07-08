"""Dashboard — terminal and web-based analytics for Sentigent.

Provides:
- sentigent dashboard: Rich terminal dashboard with stats, score, baselines, recent activity
- sentigent web: Launches a local web server with an interactive analytics dashboard

Both pull data from the local SQLite memory store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from sentigent.config import get_config
from sentigent.memory.store import MemoryStore
from sentigent.policies import load_policies


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_store() -> MemoryStore:
    """Get a MemoryStore using current config."""
    config = get_config()
    db_path = config.db_path or str(Path.home() / ".sentigent" / f"memory_{config.agent_id}.db")
    return MemoryStore(agent_id=config.agent_id, org_id=config.org_id, db_path=db_path)


def _get_dashboard_data() -> dict[str, Any]:
    """Gather all data needed for the dashboard."""
    config = get_config()
    store = _get_store()

    episode_count = store.get_episode_count()
    total_with_outcomes, correct_count = store.get_outcome_counts()
    outcome_stats = store.get_outcome_stats()
    baselines = store.get_baselines()

    score = correct_count / total_with_outcomes if total_with_outcomes > 0 else 0.0

    db_path = store.db_path
    recent_episodes = _query_recent_episodes(db_path, config.agent_id, limit=20)
    decision_dist = _query_decision_distribution(db_path, config.agent_id)
    daily_activity = _query_daily_activity(db_path, config.agent_id, days=7)
    tool_stats = _query_tool_stats(db_path, config.agent_id)
    rules = _query_rules(db_path, config.agent_id)
    impact = _query_impact_metrics(db_path, config.agent_id)
    compliance = _query_compliance_metrics(db_path, config.agent_id)

    return {
        "config": {
            "profile": config.profile,
            "agent_id": config.agent_id,
            "org_id": config.org_id,
        },
        "summary": {
            "total_episodes": episode_count,
            "total_with_outcomes": total_with_outcomes,
            "correct_count": correct_count,
            "judgment_score": score,
            "outcome_stats": outcome_stats,
        },
        "baselines": {
            name: {
                "median": b.median,
                "mean": b.mean,
                "std": b.std,
                "p5": b.p5,
                "p95": b.p95,
                "sample_size": b.sample_size,
            }
            for name, b in baselines.items()
        },
        "decision_distribution": decision_dist,
        "daily_activity": daily_activity,
        "tool_stats": tool_stats,
        "recent_episodes": recent_episodes,
        "rules": rules,
        "impact": impact,
        "compliance": compliance,
        "generated_at": datetime.now().isoformat(),
    }


def _query_recent_episodes(db_path: str, agent_id: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT trace_id, timestamp, task, decision, confidence_at_decision,
               outcome, outcome_feedback
        FROM episodes
        WHERE agent_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (agent_id, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "trace_id": row["trace_id"][:12] + "...",
            "timestamp": row["timestamp"],
            "task": (row["task"] or "")[:80],
            "decision": row["decision"],
            "confidence": row["confidence_at_decision"],
            "outcome": row["outcome"],
            "feedback": row["outcome_feedback"],
        }
        for row in rows
    ]


def _query_decision_distribution(db_path: str, agent_id: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT decision, COUNT(*) as cnt FROM episodes WHERE agent_id = ? GROUP BY decision",
        (agent_id,),
    ).fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def _query_daily_activity(db_path: str, agent_id: str, days: int = 7) -> list[dict]:
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT DATE(timestamp) as day, COUNT(*) as cnt,
               SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct,
               SUM(CASE WHEN outcome = 'incorrect' THEN 1 ELSE 0 END) as incorrect
        FROM episodes
        WHERE agent_id = ? AND timestamp >= ?
        GROUP BY DATE(timestamp)
        ORDER BY day
        """,
        (agent_id, cutoff),
    ).fetchall()
    conn.close()
    return [
        {"day": row[0], "total": row[1], "correct": row[2] or 0, "incorrect": row[3] or 0}
        for row in rows
    ]


def _query_tool_stats(db_path: str, agent_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT task, COUNT(*) as cnt,
               AVG(confidence_at_decision) as avg_conf,
               SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct,
               SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as with_outcome
        FROM episodes
        WHERE agent_id = ?
        GROUP BY task
        ORDER BY cnt DESC
        LIMIT 15
        """,
        (agent_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "tool": row[0] or "unknown",
            "count": row[1],
            "avg_confidence": round(row[2] or 0, 2),
            "correct": row[3] or 0,
            "with_outcome": row[4] or 0,
            "success_rate": round((row[3] or 0) / row[4], 2) if row[4] else None,
        }
        for row in rows
    ]


def _query_rules(db_path: str, agent_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT pattern_name, learned_action, success_rate, sample_size, last_reinforced
        FROM procedural_rules
        WHERE agent_id = ? OR agent_id IS NULL
        ORDER BY success_rate DESC
        LIMIT 20
        """,
        (agent_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "pattern": row["pattern_name"],
            "action": row["learned_action"],
            "success_rate": round(row["success_rate"], 2),
            "samples": row["sample_size"],
            "last_reinforced": row["last_reinforced"],
        }
        for row in rows
    ]


def _query_impact_metrics(db_path: str, agent_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)

    row = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision IN ('escalate', 'slow_down') AND outcome = 'correct'",
        (agent_id,),
    ).fetchone()
    disasters_prevented = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision != 'proceed'",
        (agent_id,),
    ).fetchone()
    risk_interventions = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision = 'enrich' AND outcome = 'correct'",
        (agent_id,),
    ).fetchone()
    enrichments_helped = row[0] if row else 0

    rows = conn.execute(
        "SELECT outcome, rowid FROM episodes WHERE agent_id = ? AND outcome IS NOT NULL ORDER BY timestamp ASC",
        (agent_id,),
    ).fetchall()

    score_trend = None
    if len(rows) >= 10:
        midpoint = len(rows) // 2
        first_half = rows[:midpoint]
        second_half = rows[midpoint:]
        first_score = sum(1 for r in first_half if r[0] == "correct") / len(first_half)
        second_score = sum(1 for r in second_half if r[0] == "correct") / len(second_half)
        score_trend = {
            "first_half_score": round(first_score, 3),
            "second_half_score": round(second_score, 3),
            "improvement": round(second_score - first_score, 3),
            "improving": second_score > first_score,
        }

    row = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision = 'proceed' AND outcome = 'incorrect'",
        (agent_id,),
    ).fetchone()
    mistakes_slipped = row[0] if row else 0

    recent_outcomes = conn.execute(
        "SELECT outcome FROM episodes WHERE agent_id = ? AND outcome IS NOT NULL ORDER BY timestamp DESC LIMIT 50",
        (agent_id,),
    ).fetchall()
    streak = 0
    for r in recent_outcomes:
        if r[0] == "correct":
            streak += 1
        else:
            break

    row = conn.execute(
        "SELECT COUNT(*) FROM procedural_rules WHERE agent_id = ? OR agent_id IS NULL",
        (agent_id,),
    ).fetchone()
    rules_learned = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM semantic_baselines WHERE agent_id = ? OR agent_id IS NULL",
        (agent_id,),
    ).fetchone()
    baselines_formed = row[0] if row else 0

    conn.close()
    return {
        "disasters_prevented": disasters_prevented,
        "risk_interventions": risk_interventions,
        "enrichments_helped": enrichments_helped,
        "mistakes_slipped": mistakes_slipped,
        "correct_streak": streak,
        "score_trend": score_trend,
        "rules_learned": rules_learned,
        "baselines_formed": baselines_formed,
    }


def _query_compliance_metrics(db_path: str, agent_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)

    row = conn.execute("SELECT COUNT(*) FROM episodes WHERE agent_id = ?", (agent_id,)).fetchone()
    total_actions = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision IN ('escalate', 'slow_down')",
        (agent_id,),
    ).fetchone()
    interventions = row[0] if row else 0

    compliant = total_actions - interventions
    adherence_pct = (compliant / total_actions * 100) if total_actions > 0 else 100.0

    _risk_filter = """(
        LOWER(task) LIKE '%push --force%' OR LOWER(task) LIKE '%rm -rf%'
        OR LOWER(task) LIKE '%drop table%' OR LOWER(task) LIKE '%reset --hard%'
        OR LOWER(task) LIKE '%.env%' OR LOWER(task) LIKE '%deploy%'
    )"""

    row = conn.execute(
        f"SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND {_risk_filter}",
        (agent_id,),
    ).fetchone()
    high_risk_total = row[0] if row else 0

    row = conn.execute(
        f"SELECT COUNT(*) FROM episodes WHERE agent_id = ? AND decision IN ('escalate', 'slow_down') AND {_risk_filter}",
        (agent_id,),
    ).fetchone()
    high_risk_reviewed = row[0] if row else 0
    high_risk_pct = (high_risk_reviewed / high_risk_total * 100) if high_risk_total > 0 else 100.0

    conn.close()

    try:
        policies = load_policies()
        active_policies = [p for p in policies if p.enabled]
        policy_summary = [
            {"id": p.id, "name": p.name, "severity": p.severity, "action": p.action}
            for p in active_policies
        ]
    except Exception:
        active_policies = []
        policy_summary = []

    return {
        "total_actions": total_actions,
        "compliant_actions": compliant,
        "policy_adherence_pct": round(adherence_pct, 1),
        "violations_caught": interventions,
        "high_risk_total": high_risk_total,
        "high_risk_reviewed": high_risk_reviewed,
        "high_risk_review_pct": round(high_risk_pct, 1),
        "active_policies": len(active_policies),
        "policy_summary": policy_summary,
    }


# ─── Terminal Dashboard ──────────────────────────────────────────────────────

def cmd_dashboard() -> None:
    """Rich terminal dashboard showing Sentigent analytics."""
    data = _get_dashboard_data()
    config = data["config"]
    summary = data["summary"]

    print()
    print("  \033[1;36m╔══════════════════════════════════════════════════════════════╗\033[0m")
    print("  \033[1;36m║         \033[1;37mSentigent — Judgment Analytics Dashboard\033[1;36m            ║\033[0m")
    print("  \033[1;36m╚══════════════════════════════════════════════════════════════╝\033[0m")
    print()
    print(f"  \033[90mAgent: {config['agent_id']}  |  Org: {config['org_id']}  |  Profile: {config['profile']}\033[0m")
    print()

    score = summary["judgment_score"]
    total = summary["total_with_outcomes"]
    correct = summary["correct_count"]

    if total > 0:
        bar_width = 40
        filled = int(score * bar_width)
        bar = "\033[32m█\033[0m" * filled + "\033[90m░\033[0m" * (bar_width - filled)
        score_color = "\033[32m" if score >= 0.8 else "\033[33m" if score >= 0.6 else "\033[31m"
        print(f"  \033[1mJudgment Score:\033[0m {score_color}{score:.1%}\033[0m")
        print(f"  [{bar}]")
        print(f"  \033[90m{correct} correct / {total} total decisions with outcomes\033[0m")
    else:
        print("  \033[1mJudgment Score:\033[0m \033[90mNo outcomes yet (need ~50 decisions with feedback)\033[0m")
    print()

    impact = data.get("impact", {})
    has_impact = any(impact.get(k, 0) for k in [
        "disasters_prevented", "risk_interventions", "enrichments_helped",
        "rules_learned", "baselines_formed", "correct_streak",
    ])

    if has_impact:
        print("  \033[1;33m⚡ What Sentigent Did For You\033[0m")
        print()
        dp = impact.get("disasters_prevented", 0)
        ri = impact.get("risk_interventions", 0)
        eh = impact.get("enrichments_helped", 0)
        ms = impact.get("mistakes_slipped", 0)
        streak = impact.get("correct_streak", 0)
        rl = impact.get("rules_learned", 0)
        bf = impact.get("baselines_formed", 0)

        if dp > 0:
            print(f"  \033[32m🛡  {dp} disaster{'s' if dp != 1 else ''} prevented\033[0m")
            print(f"     \033[90mRisky operations caught and correctly blocked\033[0m")
        if ri > 0:
            safe_pct = dp / ri * 100 if ri > 0 else 0
            print(f"  \033[36m🔍  {ri} risk intervention{'s' if ri != 1 else ''}\033[0m ({safe_pct:.0f}% were correct calls)")
            print(f"     \033[90mTimes Sentigent slowed down, enriched, or escalated\033[0m")
        if eh > 0:
            print(f"  \033[34m📚  {eh} enrichment{'s' if eh != 1 else ''} led to better outcomes\033[0m")
        if ms > 0:
            print(f"  \033[33m⚠   {ms} mistake{'s' if ms != 1 else ''} slipped through\033[0m")
        if streak > 0:
            streak_color = "\033[32m" if streak >= 10 else "\033[36m" if streak >= 5 else "\033[0m"
            print(f"  {streak_color}🔥  {streak} correct decisions in a row\033[0m")

        trend = impact.get("score_trend")
        if trend:
            if trend["improving"]:
                pct = trend["improvement"] * 100
                print(f"  \033[32m📈  Judgment improving: +{pct:.1f}%\033[0m")
                print(f"     \033[90m{trend['first_half_score']:.0%} → {trend['second_half_score']:.0%}\033[0m")
            elif trend["improvement"] == 0:
                print(f"  \033[36m📊  Judgment stable at {trend['second_half_score']:.0%}\033[0m")
            else:
                pct = abs(trend["improvement"]) * 100
                print(f"  \033[33m📉  Judgment dipped: -{pct:.1f}%\033[0m")

        if rl > 0 or bf > 0:
            parts = []
            if rl > 0:
                parts.append(f"{rl} rule{'s' if rl != 1 else ''}")
            if bf > 0:
                parts.append(f"{bf} baseline{'s' if bf != 1 else ''}")
            print(f"  \033[35m🧠  Learned {' + '.join(parts)}\033[0m")
        print()
    elif summary["total_episodes"] == 0:
        print("  \033[1;33m⚡ Getting Started\033[0m")
        print()
        print("  \033[90m  Sentigent is active and watching.\033[0m")
        print("  \033[90m  Just keep coding — benefits appear after ~20 decisions.\033[0m")
        print()
    elif summary["total_episodes"] > 0 and total == 0:
        print("  \033[1;33m⚡ Collecting Data\033[0m")
        print()
        print(f"  \033[90m  {summary['total_episodes']} decisions recorded, waiting for outcomes.\033[0m")
        print()

    compliance = data.get("compliance", {})
    if compliance.get("total_actions", 0) > 0:
        print("  \033[1;35m🔒 Compliance Summary\033[0m")
        print()
        adh_pct = compliance.get("policy_adherence_pct", 100)
        adh_color = "\033[32m" if adh_pct >= 95 else "\033[33m" if adh_pct >= 80 else "\033[31m"
        print(f"  {adh_color}Policy adherence: {adh_pct:.1f}%\033[0m "
              f"({compliance.get('compliant_actions', 0)}/{compliance.get('total_actions', 0)} actions compliant)")
        violations_caught = compliance.get("violations_caught", 0)
        if violations_caught > 0:
            print(f"  \033[33mViolations caught: {violations_caught}\033[0m")
        print()

    print(f"  \033[1mSummary\033[0m")
    print(f"  ├── Total episodes:  {summary['total_episodes']}")
    print(f"  ├── With outcomes:   {summary['total_with_outcomes']}")
    outcome_stats = summary["outcome_stats"]
    if outcome_stats:
        for outcome, count in sorted(outcome_stats.items()):
            icon = "✓" if outcome == "correct" else "✗" if outcome == "incorrect" else "○"
            color = "\033[32m" if outcome == "correct" else "\033[31m" if outcome == "incorrect" else "\033[90m"
            print(f"  │   {color}{icon} {outcome}: {count}\033[0m")

    decision_dist = data["decision_distribution"]
    if decision_dist:
        print(f"  └── Decisions:")
        items = sorted(decision_dist.items(), key=lambda x: -x[1])
        for i, (decision, count) in enumerate(items):
            prefix = "    └──" if i == len(items) - 1 else "    ├──"
            pct = count / summary["total_episodes"] * 100 if summary["total_episodes"] > 0 else 0
            print(f"  {prefix} {decision}: {count} ({pct:.0f}%)")
    print()

    daily = data["daily_activity"]
    if daily:
        print(f"  \033[1mActivity (last 7 days)\033[0m")
        max_count = max(d["total"] for d in daily) if daily else 1
        for d in daily:
            bar_len = int(d["total"] / max_count * 30) if max_count > 0 else 0
            bar = "\033[36m▓\033[0m" * bar_len
            correct_str = f" \033[32m+{d['correct']}\033[0m" if d["correct"] else ""
            incorrect_str = f" \033[31m-{d['incorrect']}\033[0m" if d["incorrect"] else ""
            print(f"  {d['day']}  {bar} {d['total']}{correct_str}{incorrect_str}")
        print()

    tool_stats = data["tool_stats"]
    if tool_stats:
        print(f"  \033[1mTop Tools/Tasks\033[0m")
        print(f"  {'Tool':<20} {'Count':>6} {'Avg Conf':>9} {'Success':>8}")
        print(f"  {'─'*20} {'─'*6} {'─'*9} {'─'*8}")
        for ts in tool_stats[:10]:
            success = f"{ts['success_rate']:.0%}" if ts["success_rate"] is not None else "—"
            print(f"  {ts['tool']:<20} {ts['count']:>6} {ts['avg_confidence']:>8.0%} {success:>8}")
        print()

    baselines = data["baselines"]
    if baselines:
        print(f"  \033[1mLearned Baselines\033[0m")
        for name, stats in sorted(baselines.items()):
            print(f"  ├── {name}")
            print(f"  │   median={stats['median']:.1f}  std={stats['std']:.1f}  range=[{stats['p5']:.1f}, {stats['p95']:.1f}]  n={stats['sample_size']}")
        print()

    rules = data["rules"]
    if rules:
        print(f"  \033[1mLearned Rules\033[0m")
        for r in rules[:8]:
            success_color = "\033[32m" if r["success_rate"] >= 0.8 else "\033[33m" if r["success_rate"] >= 0.5 else "\033[31m"
            print(f"  ├── {r['pattern']}")
            print(f"  │   → {r['action']}  {success_color}{r['success_rate']:.0%}\033[0m  (n={r['samples']})")
        print()

    recent = data["recent_episodes"]
    if recent:
        print(f"  \033[1mRecent Decisions\033[0m")
        for ep in recent[:8]:
            ts = ep["timestamp"][:16] if ep["timestamp"] else "?"
            decision_color = (
                "\033[32m" if ep["decision"] == "proceed" else
                "\033[33m" if ep["decision"] in ("slow_down", "enrich") else
                "\033[31m" if ep["decision"] == "escalate" else "\033[0m"
            )
            outcome_str = ""
            if ep["outcome"]:
                outcome_color = "\033[32m" if ep["outcome"] == "correct" else "\033[31m"
                outcome_str = f" → {outcome_color}{ep['outcome']}\033[0m"
            conf = f"{ep['confidence']:.0%}" if ep["confidence"] else "?"
            print(f"  \033[90m{ts}\033[0m  {decision_color}{ep['decision']:<10}\033[0m  conf={conf}{outcome_str}")
            if ep["task"]:
                print(f"  \033[90m{'':>18}{ep['task'][:60]}\033[0m")
        print()

    print(f"  \033[90mGenerated: {data['generated_at'][:19]}\033[0m")
    print(f"  \033[90mTip: Run 'sentigent web' for an interactive web dashboard\033[0m")
    print()


# ─── Web Dashboard (stdlib http.server, no extra deps) ───────────────────────

_WEB_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentigent Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --text-muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922; --cyan: #39d2c0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; padding: 24px; max-width: 1400px; margin: 0 auto; }
  h1 { font-size: 24px; font-weight: 600; margin-bottom: 4px; }
  h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; color: var(--text-muted); }
  .subtitle { color: var(--text-muted); font-size: 14px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
  .card-wide { grid-column: 1 / -1; }
  .stat-value { font-size: 36px; font-weight: 700; }
  .stat-label { color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }
  .score-bar { height: 8px; background: var(--border); border-radius: 4px; margin: 12px 0; overflow: hidden; }
  .score-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .green { color: var(--green); } .red { color: var(--red); } .yellow { color: var(--yellow); } .cyan { color: var(--cyan); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--text-muted); font-size: 12px; text-transform: uppercase; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 500; }
  .badge-proceed { background: rgba(63,185,80,0.15); color: var(--green); }
  .badge-slow_down { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .badge-enrich { background: rgba(88,166,255,0.15); color: var(--accent); }
  .badge-escalate { background: rgba(248,81,73,0.15); color: var(--red); }
  .badge-correct { background: rgba(63,185,80,0.15); color: var(--green); }
  .badge-incorrect { background: rgba(248,81,73,0.15); color: var(--red); }
  .badge-neutral { background: rgba(139,148,158,0.15); color: var(--text-muted); }
  .chart-bar { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
  .chart-label { width: 100px; font-size: 13px; color: var(--text-muted); text-align: right; }
  .chart-track { flex: 1; height: 20px; background: var(--border); border-radius: 4px; overflow: hidden; }
  .chart-fill { height: 100%; border-radius: 4px; }
  .chart-count { width: 40px; font-size: 13px; color: var(--text-muted); }
  .refresh-btn { background: var(--surface); color: var(--accent); border: 1px solid var(--border); padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .refresh-btn:hover { background: var(--border); }
  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
  .empty { color: var(--text-muted); font-style: italic; padding: 20px; text-align: center; }
  .baseline-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .baseline-item { padding: 12px; background: var(--bg); border-radius: 6px; }
  .baseline-name { font-size: 13px; color: var(--cyan); font-weight: 500; margin-bottom: 4px; }
  .baseline-value { font-size: 20px; font-weight: 600; }
  .baseline-detail { font-size: 12px; color: var(--text-muted); }
</style>
</head>
<body>
<div class="header">
  <div><h1>Sentigent Dashboard</h1><div class="subtitle" id="subtitle">Loading...</div></div>
  <button class="refresh-btn" onclick="loadData()">Refresh</button>
</div>
<div class="grid" id="stats-grid">
  <div class="card" id="score-card"></div>
  <div class="card" id="episodes-card"></div>
  <div class="card" id="outcomes-card"></div>
</div>
<div class="card" id="impact-card" style="margin-bottom:24px">
  <h2 style="color:var(--yellow)">What Sentigent Did For You</h2>
  <div id="impact-content"></div>
</div>
<div class="grid">
  <div class="card" id="activity-card"><h2>Activity (Last 7 Days)</h2><div id="activity-chart"></div></div>
  <div class="card" id="decisions-card"><h2>Decision Distribution</h2><div id="decisions-chart"></div></div>
</div>
<div class="card" id="compliance-card" style="margin-bottom:24px">
  <h2 style="color:#a371f7">&#128274; Compliance</h2>
  <div id="compliance-content"></div>
</div>
<div class="grid">
  <div class="card" id="tools-card"><h2>Tool Performance</h2><div id="tools-table"></div></div>
  <div class="card" id="baselines-card"><h2>Learned Baselines</h2><div id="baselines-content"></div></div>
</div>
<div class="grid">
  <div class="card" id="rules-card"><h2>Learned Rules</h2><div id="rules-content"></div></div>
</div>
<div class="grid">
  <div class="card card-wide" id="recent-card"><h2>Recent Decisions</h2><div id="recent-table"></div></div>
</div>
<script>
let DATA=null;
async function loadData(){
  try{const r=await fetch('/api/data');DATA=await r.json();render();}
  catch(e){document.getElementById('subtitle').textContent='Error: '+e.message;}
}
function render(){
  const c=DATA.config,s=DATA.summary;
  document.getElementById('subtitle').textContent=`Agent: ${c.agent_id} | Org: ${c.org_id} | Profile: ${c.profile} | ${DATA.generated_at.slice(0,19)}`;
  const score=s.judgment_score,sc=score>=0.8?'var(--green)':score>=0.6?'var(--yellow)':'var(--red)';
  document.getElementById('score-card').innerHTML=`<div class="stat-label">Judgment Score</div><div class="stat-value" style="color:${s.total_with_outcomes>0?sc:'var(--text-muted)'}">${s.total_with_outcomes>0?(score*100).toFixed(1)+'%':'—'}</div><div class="score-bar"><div class="score-fill" style="width:${score*100}%;background:${sc}"></div></div><div class="stat-label">${s.correct_count} correct / ${s.total_with_outcomes} evaluated</div>`;
  document.getElementById('episodes-card').innerHTML=`<div class="stat-label">Total Episodes</div><div class="stat-value cyan">${s.total_episodes}</div><div style="margin-top:8px;font-size:13px;color:var(--text-muted)">${s.total_with_outcomes} with outcomes</div>`;
  const os=s.outcome_stats||{};
  document.getElementById('outcomes-card').innerHTML=`<div class="stat-label">Outcomes</div><div style="margin-top:8px"><span class="green" style="font-size:24px;font-weight:600">${os.correct||0}</span> correct &nbsp; <span class="red" style="font-size:24px;font-weight:600">${os.incorrect||0}</span> incorrect &nbsp; <span style="color:var(--text-muted);font-size:24px;font-weight:600">${os.neutral||0}</span> neutral</div>`;

  const imp=DATA.impact||{};
  const hasImpact=imp.disasters_prevented||imp.risk_interventions||imp.rules_learned||imp.baselines_formed||imp.correct_streak;
  if(hasImpact){
    let h='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px">';
    if(imp.disasters_prevented>0)h+=`<div style="padding:16px;background:rgba(63,185,80,0.08);border-radius:8px;border-left:3px solid var(--green)"><div style="font-size:28px;font-weight:700;color:var(--green)">${imp.disasters_prevented}</div><div>Disasters Prevented</div><div style="font-size:12px;color:var(--text-muted)">Risky ops correctly blocked</div></div>`;
    if(imp.risk_interventions>0){const sp=imp.disasters_prevented>0?Math.round(imp.disasters_prevented/imp.risk_interventions*100):0;h+=`<div style="padding:16px;background:rgba(57,210,192,0.08);border-radius:8px;border-left:3px solid var(--cyan)"><div style="font-size:28px;font-weight:700;color:var(--cyan)">${imp.risk_interventions}</div><div>Risk Interventions</div><div style="font-size:12px;color:var(--text-muted)">${sp}% correct calls</div></div>`;}
    if(imp.correct_streak>0){const sc2=imp.correct_streak>=10?'var(--green)':imp.correct_streak>=5?'var(--cyan)':'var(--text)';h+=`<div style="padding:16px;background:rgba(88,166,255,0.08);border-radius:8px;border-left:3px solid ${sc2}"><div style="font-size:28px;font-weight:700;color:${sc2}">${imp.correct_streak}</div><div>Correct Streak</div></div>`;}
    if(imp.rules_learned||imp.baselines_formed){const t=(imp.rules_learned||0)+(imp.baselines_formed||0);h+=`<div style="padding:16px;background:rgba(163,113,247,0.08);border-radius:8px;border-left:3px solid #a371f7"><div style="font-size:28px;font-weight:700;color:#a371f7">${t}</div><div>Patterns Learned</div><div style="font-size:12px;color:var(--text-muted)">${imp.rules_learned||0} rules + ${imp.baselines_formed||0} baselines</div></div>`;}
    h+='</div>';
    document.getElementById('impact-content').innerHTML=h;
  }else{
    document.getElementById('impact-content').innerHTML=`<div style="padding:20px;color:var(--text-muted);text-align:center"><div style="font-size:32px">&#128640;</div><div>Sentigent is active. Keep coding to see benefits.</div></div>`;
  }

  const daily=DATA.daily_activity||[];
  if(daily.length>0){const mx=Math.max(...daily.map(d=>d.total));document.getElementById('activity-chart').innerHTML=daily.map(d=>`<div class="chart-bar"><div class="chart-label">${d.day.slice(5)}</div><div class="chart-track"><div class="chart-fill" style="width:${mx>0?d.total/mx*100:0}%;background:var(--cyan)"></div></div><div class="chart-count">${d.total}</div></div>`).join('');}
  else{document.getElementById('activity-chart').innerHTML='<div class="empty">No activity yet</div>';}

  const dd=DATA.decision_distribution||{},ddt=Object.values(dd).reduce((a,b)=>a+b,0);
  if(ddt>0){const cols={proceed:'var(--green)',slow_down:'var(--yellow)',enrich:'var(--accent)',escalate:'var(--red)'};document.getElementById('decisions-chart').innerHTML=Object.entries(dd).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="chart-bar"><div class="chart-label">${k}</div><div class="chart-track"><div class="chart-fill" style="width:${v/ddt*100}%;background:${cols[k]||'var(--text-muted)'}"></div></div><div class="chart-count">${v}</div></div>`).join('');}
  else{document.getElementById('decisions-chart').innerHTML='<div class="empty">No decisions yet</div>';}

  const comp=DATA.compliance||{};
  if(comp.total_actions>0){
    const ac=comp.policy_adherence_pct>=95?'var(--green)':comp.policy_adherence_pct>=80?'var(--yellow)':'var(--red)';
    document.getElementById('compliance-content').innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px"><div style="padding:16px;background:rgba(163,113,247,0.08);border-radius:8px;border-left:3px solid ${ac}"><div style="font-size:28px;font-weight:700;color:${ac}">${comp.policy_adherence_pct}%</div><div>Policy Adherence</div><div style="font-size:12px;color:var(--text-muted)">${comp.compliant_actions}/${comp.total_actions} compliant</div></div></div>`;
  }else{document.getElementById('compliance-content').innerHTML='<div class="empty">No actions evaluated yet</div>';}

  const tools=DATA.tool_stats||[];
  document.getElementById('tools-table').innerHTML=tools.length?`<table><tr><th>Tool</th><th>Count</th><th>Avg Conf</th><th>Success</th></tr>${tools.map(t=>`<tr><td>${t.tool}</td><td>${t.count}</td><td>${(t.avg_confidence*100).toFixed(0)}%</td><td>${t.success_rate!==null?(t.success_rate*100).toFixed(0)+'%':'—'}</td></tr>`).join('')}</table>`:'<div class="empty">No tool data yet</div>';

  const bl=DATA.baselines||{},blk=Object.keys(bl);
  document.getElementById('baselines-content').innerHTML=blk.length?`<div class="baseline-grid">${blk.map(k=>`<div class="baseline-item"><div class="baseline-name">${k}</div><div class="baseline-value">${bl[k].median.toFixed(1)}</div><div class="baseline-detail">&#177;${bl[k].std.toFixed(1)} (n=${bl[k].sample_size})</div></div>`).join('')}</div>`:'<div class="empty">No baselines learned yet</div>';

  const rules=DATA.rules||[];
  document.getElementById('rules-content').innerHTML=rules.length?`<table><tr><th>Pattern</th><th>Action</th><th>Success</th><th>Samples</th></tr>${rules.map(r=>{const rc=r.success_rate>=0.8?'green':r.success_rate>=0.5?'yellow':'red';return`<tr><td>${r.pattern}</td><td><span class="badge badge-${r.action}">${r.action}</span></td><td class="${rc}">${(r.success_rate*100).toFixed(0)}%</td><td>${r.samples}</td></tr>`}).join('')}</table>`:'<div class="empty">No rules learned yet</div>';

  const recent=DATA.recent_episodes||[];
  document.getElementById('recent-table').innerHTML=recent.length?`<table><tr><th>Time</th><th>Task</th><th>Decision</th><th>Confidence</th><th>Outcome</th></tr>${recent.map(ep=>`<tr><td style="white-space:nowrap;color:var(--text-muted)">${(ep.timestamp||'').slice(0,16)}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${ep.task||'—'}</td><td><span class="badge badge-${ep.decision}">${ep.decision}</span></td><td>${ep.confidence?(ep.confidence*100).toFixed(0)+'%':'—'}</td><td>${ep.outcome?'<span class="badge badge-'+ep.outcome+'">'+ep.outcome+'</span>':'—'}</td></tr>`).join('')}</table>`:'<div class="empty">No decisions recorded yet</div>';
}
loadData();
setInterval(loadData,30000);
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the Sentigent web dashboard."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_WEB_DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/data":
            try:
                data = _get_dashboard_data()
                payload = json.dumps(data, default=str)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def cmd_web(port: int = 7777) -> None:
    """Launch the Sentigent web dashboard."""
    print()
    print("  \033[1mSentigent Web Dashboard\033[0m")
    print()
    config = get_config()
    print(f"  Agent: {config.agent_id}  |  Org: {config.org_id}  |  Profile: {config.profile}")
    print()
    print(f"  \033[36m→ http://localhost:{port}\033[0m")
    print()
    print("  \033[90mAuto-refreshes every 30s. Press Ctrl+C to stop.\033[0m")
    print()

    try:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    except Exception:
        pass

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        server.shutdown()
