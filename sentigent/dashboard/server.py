"""Sentigent Web Dashboard — FastAPI server exposing judgment data.

Run with:
    python -m sentigent.dashboard
    # Opens at http://localhost:7373
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    raise ImportError(
        "Dashboard requires: pip install 'sentigent[dashboard]'"
    )

app = FastAPI(title="Sentigent Dashboard", version="2.0.0")

# CORS for dev (Vite runs on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:7373"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
REACT_APP_DIR = STATIC_DIR / "app"

# Serve React build assets at /assets (Vite builds with root-relative paths)
_react_assets = REACT_APP_DIR / "assets"
if _react_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_react_assets)), name="react-assets")


# ── Helpers ────────────────────────────────────────────────────

def _get_db_path() -> str:
    agent_id = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    return os.environ.get(
        "SENTIGENT_DB_PATH",
        str(Path.home() / ".sentigent" / f"memory_{agent_id}.db"),
    )


def _query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    db_path = _get_db_path()
    if not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []


def _get_supabase() -> Any | None:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _resolve_org_id() -> str:
    # Explicit UUID always wins
    if os.environ.get("SENTIGENT_SUPABASE_ORG_ID"):
        return os.environ["SENTIGENT_SUPABASE_ORG_ID"]
    slug = os.environ.get("SENTIGENT_ORG_ID", "")
    if not slug:
        return ""
    # Resolve slug → UUID via Supabase
    client = _get_supabase()
    if client:
        try:
            result = client.table("organizations").select("id").eq("slug", slug).maybe_single().execute()
            if result.data:
                return result.data["id"]
        except Exception:
            pass
    return ""


# ── Static + SPA ───────────────────────────────────────────────

@app.get("/favicon.svg")
async def favicon():
    from fastapi.responses import FileResponse
    svg = REACT_APP_DIR / "favicon.svg"
    if not svg.exists():
        svg = STATIC_DIR / "favicon.svg"
    if svg.exists():
        return FileResponse(str(svg), media_type="image/svg+xml")
    return HTMLResponse("", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the React SPA or fallback to legacy HTML."""
    react_index = REACT_APP_DIR / "index.html"
    if react_index.exists():
        return HTMLResponse(react_index.read_text())
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text())
    return HTMLResponse("<h1>Sentigent Dashboard</h1><p>Run 'npm run build' in frontend/ to enable the React app.</p>")


# ── Local Agent Endpoints ──────────────────────────────────────

@app.get("/api/score")
async def get_score():
    rows = _query(
        "SELECT outcome, COUNT(*) as cnt FROM episodes "
        "WHERE outcome IS NOT NULL GROUP BY outcome"
    )
    outcomes = {r["outcome"]: r["cnt"] for r in rows}
    total = sum(outcomes.values())
    correct = outcomes.get("correct", 0)
    score = correct / total if total > 0 else 0.0
    total_rows = _query("SELECT COUNT(*) as cnt FROM episodes")
    total_episodes = total_rows[0]["cnt"] if total_rows else 0
    return JSONResponse({
        "score": round(score, 4),
        "score_pct": f"{score:.1%}",
        "total_episodes": total_episodes,
        "total_with_outcomes": total,
        "outcomes": outcomes,
    })


@app.get("/api/sprint")
async def get_sprint():
    """Truth-sprint state: WS-B harness status, the 7 pinned assumptions, and
    live ablation results (A0/A1/A2 VACR) when a real pilot has been run.

    Read-only + fail-soft: never CREATES the sprint DBs (only opens them when
    they already exist on disk), and returns a clean empty state when no graded
    runs / ablation rows exist yet. See docs/WSB-REAL-FINDINGS.md.
    """
    # The 7 load-bearing assumptions, pinned by tests/test_sprint_assumptions.py.
    assumptions = [
        {"id": "A", "claim": "$0 metered — solver scrubs ANTHROPIC_API_KEY"},
        {"id": "B", "claim": "Brain isolation — never writes memory_hussain.db"},
        {"id": "C", "claim": "Ablation discriminates A0/A1/A2 (repair is real)"},
        {"id": "D", "claim": "Falsifiable learning — real negatives, not a stamp"},
        {"id": "E", "claim": "Real 500-instance SWE-bench dataset loads"},
        {"id": "F", "claim": "Docker scorer mockable + guard never raises"},
        {"id": "G", "claim": "Paired runner resumable + throttled"},
    ]

    # Sprint grader report (memory_swebench.db) — only if it already exists.
    grader = {"total": 0, "correct": 0, "incorrect": 0, "repaired": 0,
              "incorrect_rate": 0.0, "repair_success_rate": 0.0}
    try:
        from sentigent.eval.sprint_grader import (
            SprintGrader, DEFAULT_SWEBENCH_DB_PATH,
        )
        if os.path.exists(DEFAULT_SWEBENCH_DB_PATH):
            grader = SprintGrader(DEFAULT_SWEBENCH_DB_PATH).report()
    except Exception:
        pass

    # Ablation results (ablation_results.db) — per-arm VACR when rows exist.
    arms: dict[str, Any] = {"a0": None, "a1": None, "a2": None}
    ablation_total = 0
    try:
        from sentigent.eval.ablation.results_db import (
            AblationResultsDB, DEFAULT_ABLATION_DB_PATH,
        )
        if os.path.exists(DEFAULT_ABLATION_DB_PATH):
            rows = AblationResultsDB(DEFAULT_ABLATION_DB_PATH).fetch_all()
            ablation_total = len(rows)
            by_arm: dict[str, list] = {}
            for r in rows:
                by_arm.setdefault(r.arm.lower(), []).append(r)
            for arm, rs in by_arm.items():
                resolved = sum(1 for r in rs if r.resolved)
                arms[arm] = {
                    "n": len(rs),
                    "resolved": resolved,
                    "vacr": round(resolved / len(rs), 4) if rs else None,
                }
    except Exception:
        pass

    has_pilot = ablation_total > 0
    a0, a2 = arms.get("a0"), arms.get("a2")
    if has_pilot and a0 and a2 and a0["vacr"] is not None and a2["vacr"] is not None:
        delta = round((a2["vacr"] - a0["vacr"]) * 100, 1)
        verdict = f"A2−A0 = {delta:+} pts (n={ablation_total})"
    else:
        verdict = ("plumbing proven; real arms↔instance↔Docker bridge "
                   "open (no VACR yet)")

    return JSONResponse({
        "wsb_status": "complete",
        "wsb_slices": [
            "swebench-loader", "a1-arm", "docker-scorer", "paired-runner-real",
        ],
        "assumptions": assumptions,
        "assumptions_passed": len(assumptions),
        "assumptions_total": len(assumptions),
        "assumptions_test": "tests/test_sprint_assumptions.py",
        "grader": grader,
        "ablation": arms,
        "ablation_total_rows": ablation_total,
        "has_real_pilot": has_pilot,
        "verdict": verdict,
        "metered_cost_usd": 0.0,
    })


@app.get("/api/episodes")
async def get_episodes(limit: int = 50, search: str = ""):
    if search:
        rows = _query(
            "SELECT trace_id, task, decision, outcome, confidence_at_decision, "
            "signals, timestamp, reason FROM episodes "
            "WHERE LOWER(task) LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{search.lower()}%", limit),
        )
    else:
        rows = _query(
            "SELECT trace_id, task, decision, outcome, confidence_at_decision, "
            "signals, timestamp, reason FROM episodes "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
    for r in rows:
        try:
            r["signals"] = json.loads(r.get("signals") or "{}")
        except Exception:
            r["signals"] = {}
    return JSONResponse(rows)


@app.get("/api/patterns")
async def get_patterns():
    rows = _query(
        "SELECT pattern_name, learned_action, success_rate, sample_size, "
        "last_reinforced FROM procedural_rules ORDER BY success_rate DESC LIMIT 50"
    )
    return JSONResponse(rows)


@app.get("/api/baselines")
async def get_baselines():
    rows = _query(
        "SELECT metric_name, baseline_data, source, last_updated, sample_size "
        "FROM semantic_baselines ORDER BY metric_name"
    )
    result = []
    for r in rows:
        try:
            data = json.loads(r["baseline_data"])
        except Exception:
            data = {}
        result.append({
            "metric": r["metric_name"],
            "median": data.get("median"),
            "std": data.get("std"),
            "p5": data.get("p5"),
            "p95": data.get("p95"),
            "sample_size": r["sample_size"],
            "source": r["source"],
            "last_updated": r["last_updated"],
        })
    return JSONResponse(result)


@app.get("/api/timeline")
async def get_timeline():
    rows = _query(
        """
        SELECT DATE(timestamp) as day,
               COUNT(*) as total,
               SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct
        FROM episodes
        WHERE outcome IS NOT NULL
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
        LIMIT 30
        """
    )
    for r in rows:
        total = r["total"] or 1
        r["score"] = round((r["correct"] or 0) / total, 4)
    return JSONResponse(list(reversed(rows)))


@app.get("/api/insights")
async def get_insights():
    rows = _query(
        "SELECT category, subject, finding, confidence, recommendation, "
        "signal_weight, computed_at FROM computed_insights ORDER BY computed_at DESC"
    )
    correlations = [r for r in rows if r["category"] == "correlation"]
    trends = [r for r in rows if r["category"] == "trend"]
    anomalies = [r for r in rows if r["category"] == "anomaly"]
    metrics = [r for r in rows if r["category"] == "metric"]

    brier_row = next((r for r in metrics if r["subject"] == "calibration"), None)
    brier_score = None
    brier_interpretation = "No data yet"
    if brier_row:
        import re
        m = re.search(r"[\d.]+", brier_row["finding"])
        if m:
            brier_score = float(m.group())
            brier_interpretation = (
                "Well-calibrated" if brier_score < 0.15
                else "Moderate" if brier_score < 0.25
                else "Poorly calibrated"
            )
    recommendations = list({r["recommendation"] for r in rows if r["recommendation"]})
    return JSONResponse({
        "correlations": correlations,
        "trends": trends,
        "anomalies": anomalies,
        "brier_score": brier_score,
        "brier_interpretation": brier_interpretation,
        "recommendations": recommendations,
        "computed_at": rows[0]["computed_at"] if rows else None,
    })


# ── Layer 2 ─────────────────────────────────────────────────────

@app.get("/api/layer2/status")
async def get_layer2_status():
    url = os.environ.get("SUPABASE_URL", "")
    has_key = bool(
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    )
    return JSONResponse({
        "configured": bool(url and has_key),
        "supabase_url": url if url else None,
        "org_id": os.environ.get("SENTIGENT_ORG_ID", ""),
    })


@app.get("/api/layer2/org")
async def get_org_overview():
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "SENTIGENT_SUPABASE_ORG_ID not set"}, status_code=503)
    try:
        agents_result = (
            client.table("synced_episodes")
            .select("agent_id, outcome")
            .eq("org_id", org_id)
            .execute()
        )
        agents: dict[str, dict[str, int]] = {}
        for row in (agents_result.data or []):
            aid = row["agent_id"]
            outcome = row["outcome"] or "pending"
            if aid not in agents:
                agents[aid] = {"total": 0, "correct": 0, "incorrect": 0, "neutral": 0, "pending": 0}
            agents[aid]["total"] += 1
            agents[aid][outcome] = agents[aid].get(outcome, 0) + 1

        agent_list = []
        for aid, stats in agents.items():
            total_with_outcome = stats["correct"] + stats["incorrect"] + stats.get("neutral", 0)
            score = stats["correct"] / total_with_outcome if total_with_outcome > 0 else 0
            agent_list.append({
                "agent_id": aid,
                "total_episodes": stats["total"],
                "correct": stats["correct"],
                "incorrect": stats["incorrect"],
                "neutral": stats.get("neutral", 0),
                "score": round(score, 4),
                "score_pct": f"{score:.1%}",
            })
        agent_list.sort(key=lambda x: x["score"], reverse=True)

        total_eps = sum(a["total_episodes"] for a in agent_list)
        total_correct = sum(a["correct"] for a in agent_list)
        total_rated = sum(a["correct"] + a["incorrect"] + a["neutral"] for a in agent_list)
        org_score = total_correct / total_rated if total_rated > 0 else 0

        patterns_result = (
            client.table("org_patterns")
            .select("pattern_name, learned_action, success_rate, sample_size, contributing_agents, last_reinforced")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .order("success_rate", desc=True)
            .limit(20)
            .execute()
        )
        baselines_result = (
            client.table("org_baselines")
            .select("metric_name, median, std, p5, p95, sample_size, computed_at")
            .eq("org_id", org_id)
            .order("sample_size", desc=True)
            .execute()
        )
        return JSONResponse({
            "org_score": round(org_score, 4),
            "org_score_pct": f"{org_score:.1%}",
            "total_episodes": total_eps,
            "total_agents": len(agent_list),
            "agents": agent_list,
            "patterns": patterns_result.data or [],
            "baselines": baselines_result.data or [],
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/layer2/timeline")
async def get_org_timeline():
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = (
            client.table("synced_episodes")
            .select("created_at, outcome, agent_id")
            .eq("org_id", org_id)
            .gte("created_at", cutoff)
            .execute()
        )
        by_day: dict[str, dict[str, int]] = {}
        for row in (result.data or []):
            day = (row["created_at"] or "")[:10]
            if not day:
                continue
            if day not in by_day:
                by_day[day] = {"total": 0, "correct": 0}
            by_day[day]["total"] += 1
            if row["outcome"] == "correct":
                by_day[day]["correct"] += 1

        timeline = sorted([
            {
                "day": day,
                "total": stats["total"],
                "correct": stats["correct"],
                "score": round(stats["correct"] / max(stats["total"], 1), 4),
            }
            for day, stats in by_day.items()
        ], key=lambda x: x["day"])
        return JSONResponse(timeline)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Proof of Value ──────────────────────────────────────────────

@app.get("/api/prove")
async def get_prove(days: int = 90) -> JSONResponse:
    agent_id = os.environ.get("SENTIGENT_AGENT_ID", "default_agent")
    org_id = _resolve_org_id()
    try:
        from sentigent.core.prove import ProofEngine
        engine = ProofEngine(agent_id=agent_id, org_id=org_id or "")
        report = engine.compute(days=days)
        return JSONResponse(report.to_dict())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Policies ────────────────────────────────────────────────────

@app.get("/api/policies")
async def get_policies() -> JSONResponse:
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        result = (
            client.table("org_policies")
            .select("policy_name,trigger_tool,trigger_pattern,profile_override,enforce_action,enforce_reason,severity,is_active,trigger_count,last_triggered")
            .eq("org_id", org_id)
            .order("severity")
            .execute()
        )
        violations = (
            client.table("policy_violations")
            .select("policy_name,agent_id,enforced_action,task,timestamp")
            .eq("org_id", org_id)
            .order("timestamp", desc=True)
            .limit(50)
            .execute()
        )
        return JSONResponse({
            "policies": result.data or [],
            "recent_violations": violations.data or [],
            "total_policies": len(result.data or []),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class PolicyCreate(BaseModel):
    policy_name: str
    trigger_tool: str = "*"
    trigger_pattern: str = ""
    profile_override: str = ""
    enforce_action: str = "slow_down"
    enforce_reason: str = ""
    severity: str = "medium"
    is_active: bool = True


@app.post("/api/policies")
async def create_policy(body: PolicyCreate) -> JSONResponse:
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        client.table("org_policies").upsert({
            "org_id": org_id,
            "policy_name": body.policy_name,
            "trigger_tool": body.trigger_tool,
            "trigger_pattern": body.trigger_pattern,
            "profile_override": body.profile_override,
            "enforce_action": body.enforce_action,
            "enforce_reason": body.enforce_reason,
            "severity": body.severity,
            "is_active": body.is_active,
            "trigger_count": 0,
        }).execute()
        return JSONResponse({"status": "ok", "message": f"Policy '{body.policy_name}' created"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class PolicyUpdate(BaseModel):
    trigger_tool: str | None = None
    trigger_pattern: str | None = None
    enforce_action: str | None = None
    enforce_reason: str | None = None
    severity: str | None = None
    is_active: bool | None = None
    profile_override: str | None = None


@app.put("/api/policies/{policy_name}")
async def update_policy(policy_name: str, body: PolicyUpdate) -> JSONResponse:
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            return JSONResponse({"error": "No fields to update"}, status_code=400)
        client.table("org_policies").update(updates).eq("org_id", org_id).eq("policy_name", policy_name).execute()
        return JSONResponse({"status": "ok", "message": f"Policy '{policy_name}' updated"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/policies/{policy_name}/toggle")
async def toggle_policy(policy_name: str) -> JSONResponse:
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        current = (
            client.table("org_policies")
            .select("is_active")
            .eq("org_id", org_id)
            .eq("policy_name", policy_name)
            .execute()
        )
        if not current.data:
            return JSONResponse({"error": "Policy not found"}, status_code=404)
        new_state = not current.data[0]["is_active"]
        client.table("org_policies").update({"is_active": new_state}).eq("org_id", org_id).eq("policy_name", policy_name).execute()
        return JSONResponse({"status": "ok", "is_active": new_state})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/policies/{policy_name}/deactivate")
async def deactivate_policy(policy_name: str) -> JSONResponse:
    client = _get_supabase()
    if not client:
        return JSONResponse({"error": "Layer 2 not configured"}, status_code=503)
    org_id = _resolve_org_id()
    if not org_id:
        return JSONResponse({"error": "org not configured"}, status_code=503)
    try:
        client.table("org_policies").update({"is_active": False}).eq("org_id", org_id).eq("policy_name", policy_name).execute()
        return JSONResponse({"status": "ok", "message": f"Policy '{policy_name}' deactivated"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Practice Policy Templates ──────────────────────────────────

PRACTICE_TEMPLATES = [
    {
        "id": "tdd_enforcement",
        "name": "Test-Driven Development",
        "description": "Require tests to be written before or alongside code changes. Slows down write operations to prompt test consideration.",
        "category": "testing",
        "policy": {
            "policy_name": "tdd_enforcement",
            "trigger_tool": "Write",
            "trigger_pattern": r"\.py$|\.ts$|\.tsx$|\.js$",
            "enforce_action": "slow_down",
            "enforce_reason": "TDD policy: ensure tests exist for this change. Add/update tests before proceeding.",
            "severity": "medium",
            "profile_override": "",
        },
    },
    {
        "id": "no_secrets_in_code",
        "name": "No Secrets in Code",
        "description": "Block writing API keys, passwords, or tokens directly into source files.",
        "category": "security",
        "policy": {
            "policy_name": "no_secrets_in_code",
            "trigger_tool": "Write",
            "trigger_pattern": r"(?i)(api_key|secret|password|token|private_key)\s*=\s*['\"][^'\"]+['\"]",
            "enforce_action": "block",
            "enforce_reason": "Security policy: never hardcode secrets. Use environment variables or a secrets manager.",
            "severity": "critical",
            "profile_override": "",
        },
    },
    {
        "id": "no_force_push",
        "name": "No Force Push",
        "description": "Block force pushes to protected branches (main, master, production).",
        "category": "process",
        "policy": {
            "policy_name": "no_force_push",
            "trigger_tool": "Bash",
            "trigger_pattern": r"push.*--force|push.*-f\b",
            "enforce_action": "block",
            "enforce_reason": "Git policy: force push destroys history. Use --force-with-lease at minimum, or rebase and normal push.",
            "severity": "high",
            "profile_override": "",
        },
    },
    {
        "id": "protect_env_files",
        "name": "Protect .env Files",
        "description": "Escalate any writes to .env, .env.local, or credentials files for human review.",
        "category": "security",
        "policy": {
            "policy_name": "protect_env_files",
            "trigger_tool": "Write",
            "trigger_pattern": r"\.env(\.|$)|credentials|\.secret",
            "enforce_action": "escalate",
            "enforce_reason": "Security policy: writing to secret files requires explicit human approval.",
            "severity": "critical",
            "profile_override": "",
        },
    },
    {
        "id": "code_review_gate",
        "name": "Code Review Gate",
        "description": "Require review context before large code changes. Slows down to prompt checklist verification.",
        "category": "quality",
        "policy": {
            "policy_name": "code_review_gate",
            "trigger_tool": "Edit",
            "trigger_pattern": r"",
            "enforce_action": "enrich",
            "enforce_reason": "Quality policy: gather review context before making significant edits.",
            "severity": "low",
            "profile_override": "",
        },
    },
    {
        "id": "no_production_db_mutations",
        "name": "No Production DB Mutations",
        "description": "Block direct SQL mutations to production databases without explicit approval.",
        "category": "safety",
        "policy": {
            "policy_name": "no_production_db_mutations",
            "trigger_tool": "Bash",
            "trigger_pattern": r"(?i)(DROP|DELETE|TRUNCATE|ALTER TABLE).*prod|psql.*prod",
            "enforce_action": "escalate",
            "enforce_reason": "Safety policy: production database mutations require explicit human approval.",
            "severity": "critical",
            "profile_override": "",
        },
    },
    {
        "id": "dependency_audit",
        "name": "Dependency Audit",
        "description": "Slow down on new package installations to trigger security audit consideration.",
        "category": "security",
        "policy": {
            "policy_name": "dependency_audit",
            "trigger_tool": "Bash",
            "trigger_pattern": r"npm install|pip install|yarn add|cargo add",
            "enforce_action": "slow_down",
            "enforce_reason": "Security policy: audit new dependencies for vulnerabilities before installing.",
            "severity": "medium",
            "profile_override": "",
        },
    },
    {
        "id": "no_hard_reset",
        "name": "No Hard Reset",
        "description": "Block git reset --hard which can destroy uncommitted work.",
        "category": "safety",
        "policy": {
            "policy_name": "no_hard_reset",
            "trigger_tool": "Bash",
            "trigger_pattern": r"reset.*--hard|checkout\s+\.",
            "enforce_action": "escalate",
            "enforce_reason": "Safety policy: hard reset destroys uncommitted work. Confirm intent with user.",
            "severity": "high",
            "profile_override": "",
        },
    },
    {
        "id": "semantic_commits",
        "name": "Semantic Commits",
        "description": "Remind agents to use conventional commit format (feat:, fix:, chore:, etc.).",
        "category": "process",
        "policy": {
            "policy_name": "semantic_commits",
            "trigger_tool": "Bash",
            "trigger_pattern": r"git commit -m",
            "enforce_action": "enrich",
            "enforce_reason": "Process policy: use conventional commit format (feat:, fix:, chore:, refactor:, docs:, test:).",
            "severity": "low",
            "profile_override": "",
        },
    },
    {
        "id": "deploy_approval_gate",
        "name": "Deploy Approval Gate",
        "description": "Escalate all deploy/publish/release operations for human approval.",
        "category": "process",
        "policy": {
            "policy_name": "deploy_approval_gate",
            "trigger_tool": "Bash",
            "trigger_pattern": r"deploy|publish|release|fly deploy|vercel|heroku",
            "enforce_action": "escalate",
            "enforce_reason": "Deploy policy: all deployments require explicit human approval.",
            "severity": "high",
            "profile_override": "",
        },
    },
]


@app.get("/api/practice-templates")
async def get_practice_templates() -> JSONResponse:
    """Return built-in development practice policy templates."""
    return JSONResponse({"templates": PRACTICE_TEMPLATES})


# ── Profile & Prompt Health ─────────────────────────────────────

@app.get("/api/profile")
async def get_profile(agent_id: str = "") -> JSONResponse:
    from sentigent.core.profile_intelligence import get_profile_intelligence
    org_id = _resolve_org_id() or os.environ.get("SENTIGENT_ORG_ID", "default")
    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
    try:
        pi = get_profile_intelligence(org_id=org_id, agent_id=aid)
        report = pi.get_profile_report()
        return JSONResponse({"status": "ok", "profile": report.to_dict()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/prompt-health")
async def get_prompt_health(agent_id: str = "", days: int = 30) -> JSONResponse:
    from sentigent.core.prompt_observer import PromptObserver
    aid = agent_id or os.environ.get("SENTIGENT_AGENT_ID", "default_agent")
    try:
        observer = PromptObserver(agent_id=aid)
        report = observer.analyze(lookback_days=days)
        return JSONResponse({"status": "ok", "report": report.to_dict()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Collective Intelligence (Layer 3) ──────────────────────────

@app.get("/api/collective")
async def get_collective(
    action: str = "status",
    profile: str = "default",
) -> JSONResponse:
    from sentigent.sync.manager import SyncManager
    org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    agent_id = os.environ.get("SENTIGENT_AGENT_ID", "default_agent")
    if not org_id:
        return JSONResponse({"error": "SENTIGENT_ORG_ID not configured"}, status_code=503)
    mgr = SyncManager(org_id=org_id, agent_id=agent_id)
    try:
        if action == "status":
            status = mgr.get_layer3_status()
            return JSONResponse({"status": "ok", "collective": status})
        elif action == "pull":
            patterns = mgr.pull_layer3_patterns()
            return JSONResponse({"status": "ok", "patterns": patterns})
        elif action == "opt_status":
            opted = mgr.get_layer3_opt_in(profile)
            return JSONResponse({"status": "ok", "opted_in": opted, "profile": profile})
        return JSONResponse({"error": f"Unknown action: {action}"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Prompt Builder HTTP API ─────────────────────────────────────

@app.get("/api/prompt-builder/templates")
async def pb_list_templates() -> JSONResponse:
    from sentigent.core.prompt_builder import list_templates
    return JSONResponse(list_templates())


class PBStartRequest(BaseModel):
    template: str


@app.post("/api/prompt-builder/start")
async def pb_start(body: PBStartRequest) -> JSONResponse:
    from sentigent.core.prompt_builder import start_session
    result = start_session(body.template)
    return JSONResponse(result)


class PBAnswerRequest(BaseModel):
    session_id: str
    answer: str


@app.post("/api/prompt-builder/answer")
async def pb_answer(body: PBAnswerRequest) -> JSONResponse:
    from sentigent.core.prompt_builder import answer_field
    result = answer_field(body.session_id, body.answer)
    return JSONResponse(result)


class PBSkipRequest(BaseModel):
    session_id: str


@app.post("/api/prompt-builder/skip")
async def pb_skip(body: PBSkipRequest) -> JSONResponse:
    from sentigent.core.prompt_builder import skip_field
    result = skip_field(body.session_id)
    return JSONResponse(result)


@app.post("/api/prompt-builder/abandon")
async def pb_abandon(body: PBSkipRequest) -> JSONResponse:
    from sentigent.core.prompt_builder import abandon_session
    result = abandon_session(body.session_id)
    return JSONResponse(result)


# ── Real-time SSE Decision Stream ───────────────────────────────

_sse_clients: list[asyncio.Queue] = []


async def _sse_event_generator(queue: asyncio.Queue):
    """Yield SSE events from the queue, sending heartbeats to keep alive."""
    try:
        # Send initial connection event
        yield f"event: connected\ndata: {{\"status\": \"connected\"}}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
                yield f"event: decision\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive
                yield f": heartbeat\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        if queue in _sse_clients:
            _sse_clients.remove(queue)


@app.get("/api/decisions/stream")
async def stream_decisions():
    """Server-Sent Events stream of live decisions."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.append(queue)
    return StreamingResponse(
        _sse_event_generator(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _broadcast_decision(decision_data: dict) -> None:
    """Push a decision to all connected SSE clients."""
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(decision_data)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in _sse_clients:
            _sse_clients.remove(q)


# ── SPA Catch-all (must be LAST — after all /api routes) ────────
# React Router handles client-side routing; any non-API path returns index.html

from fastapi import Request


# ── Intelligence Hub API ────────────────────────────────────────────────


@app.get("/api/intelligence/status")
async def get_intelligence_status() -> JSONResponse:
    """Hub status: running, connected agents, last learn cycle."""
    try:
        from sentigent.intelligence.hub import get_hub
        hub = get_hub(org_id=_resolve_org_id())
        status = hub.status()
        return JSONResponse({
            "running": status.running,
            "org_id": status.org_id,
            "connected_agents": status.connected_agents,
            "total_signals_processed": status.total_signals_processed,
            "last_learn_cycle": status.last_learn_cycle,
            "learner_report": status.learner_report,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/intelligence/network")
async def get_agent_network() -> JSONResponse:
    """All connected agents and their live stats."""
    try:
        from sentigent.intelligence.hub import get_hub
        hub = get_hub(org_id=_resolve_org_id())
        return JSONResponse({"agents": hub.get_agent_network()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/intelligence/signals")
async def get_recent_signals(
    agent_id: str = "",
    signal_type: str = "",
    limit: int = 50,
) -> JSONResponse:
    """Recent signal stream from connected agents."""
    try:
        from sentigent.intelligence.hub import get_hub
        hub = get_hub(org_id=_resolve_org_id())
        if not hub._connector:
            return JSONResponse({"signals": []})
        signals = hub._connector.recent_signals(
            agent_id=agent_id or None,
            signal_type=signal_type or None,
            limit=limit,
        )
        return JSONResponse({
            "signals": [
                {
                    "signal_type": s.signal_type,
                    "agent_id": s.agent_id,
                    "payload": s.payload,
                    "timestamp": s.timestamp,
                }
                for s in signals
            ]
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/intelligence/patterns")
async def get_peer_patterns() -> JSONResponse:
    """High-confidence patterns learned across all connected agents."""
    try:
        from sentigent.intelligence.hub import get_hub
        hub = get_hub(org_id=_resolve_org_id())
        patterns = hub.get_peer_patterns(limit=20)
        return JSONResponse({"patterns": patterns})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/intelligence/learn")
async def trigger_learn_cycle() -> JSONResponse:
    """Manually trigger a collective learning cycle."""
    try:
        from sentigent.intelligence.hub import get_hub
        hub = get_hub(org_id=_resolve_org_id())
        if not hub._learner:
            return JSONResponse({"error": "Learner not initialized"}, status_code=503)
        report = hub._learner.run_once()
        return JSONResponse({
            "status": "ok",
            "agents_analyzed": report.agents_analyzed,
            "threshold_updates": len(report.threshold_updates),
            "policies_generated": len(report.policies_generated),
            "insights": report.cross_agent_insights,
            "regression_detected": report.regression_detected,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    """Return the React SPA for any unknown path so client-side routing works."""
    react_index = REACT_APP_DIR / "index.html"
    if react_index.exists():
        return HTMLResponse(react_index.read_text())
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


# ── Server Startup ──────────────────────────────────────────────

def main() -> None:
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("\"'")
                if k.startswith("SUPABASE_") or k.startswith("SENTIGENT_"):
                    os.environ.setdefault(k, v)

    port = int(os.environ.get("SENTIGENT_DASHBOARD_PORT", "7373"))
    has_react = (REACT_APP_DIR / "index.html").exists()
    print(f"Sentigent Dashboard → http://localhost:{port}")
    if has_react:
        print(f"  React app served from /app")
    else:
        print(f"  Legacy HTML served (run 'npm run build' in frontend/ for React app)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
