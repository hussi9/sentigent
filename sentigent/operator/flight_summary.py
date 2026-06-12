"""Flight summary — the rewarding panel you see when a fly-mode run finishes.

Fly mode used to end in a wall of event JSON. This replaces that with one clean, scannable
panel: what your clone did THIS flight, and what it's become ALL TIME — read live from the local
brain. Every number is real (counts straight from the store); nothing is modeled or invented
(see DECISIONS.md D-008). Pure read-over-store. Never raises.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional


def _scalar(db: str, sql: str, params: tuple = ()) -> int:
    try:
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _sum_usd(db: str, sql: str, params: tuple = ()) -> float:
    try:
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(sql, params).fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
        finally:
            conn.close()
    except Exception:
        return 0.0


def cumulative_stats(store: Any) -> dict:
    """Lifetime vital signs of the clone. All real, all local."""
    db = store.db_path
    dna: dict = {}
    try:
        conn = sqlite3.connect(db)
        try:
            for kind, n in conn.execute("SELECT kind, COUNT(*) FROM decision_events GROUP BY kind"):
                dna[str(kind)] = int(n)
        finally:
            conn.close()
    except Exception:
        dna = {}

    try:
        precedents = len(store.get_precedents() or [])
    except Exception:
        precedents = 0
    try:
        practices = len(store.get_practices() or [])
    except Exception:
        practices = _scalar(db, "SELECT COUNT(*) FROM practices")

    cal = {}
    try:
        cal = store.get_calibration() or {}
    except Exception:
        cal = {}
    cal_total = sum(int(v.get("total", 0)) for v in cal.values())
    cal_correct = 0
    for v in cal.values():
        c = v.get("correct")
        cal_correct += int(c) if c is not None else round(float(v.get("rate", 0)) * int(v.get("total", 0)))
    cal_acc = (cal_correct / cal_total) if cal_total else None

    return {
        "episodes": _scalar(db, "SELECT COUNT(*) FROM episodes"),
        "dna": dna,
        "decisions": sum(dna.values()),
        "precedents": precedents,
        "practices": practices,
        "calibration_accuracy": cal_acc,
        "cost_spent_usd": round(_sum_usd(db, "SELECT SUM(cost_usd) FROM cost_events"), 2),
        "cost_calls": _scalar(db, "SELECT COUNT(*) FROM cost_events"),
    }


def session_stats(store: Any, since_ts: float = 0.0) -> dict:
    """What changed in the brain since `since_ts` — the achievement of this flight."""
    db = store.db_path
    return {
        "precedents_gained": _scalar(db, "SELECT COUNT(*) FROM operator_precedents WHERE ts>=?", (since_ts,)),
        "escalations_answered": _scalar(
            db, "SELECT COUNT(*) FROM escalations WHERE answered_at IS NOT NULL AND answered_at>=?", (since_ts,)),
        "decisions_made": _scalar(db, "SELECT COUNT(*) FROM decision_events WHERE ts>=?", (since_ts,)),
    }


def _bar(n: int, peak: int, width: int = 20) -> str:
    if peak <= 0:
        return ""
    return "█" * max(1, round(n / peak * width)) if n else ""


def render_panel(cumulative: dict, session: Optional[dict] = None,
                 extras: Optional[dict] = None) -> str:
    """Render the clean flight panel. `extras` lets the caller add flight-only facts it knows
    (e.g. {'checks_green': 20, 'commits': 3, 'autonomy_rate': 1.0, 'auto_resolved': 6, 'asked': 1})."""
    extras = extras or {}
    rule = "━" * 60
    out: list[str] = [rule, "  🛫  FLIGHT COMPLETE — your clone flew this session as you", rule, ""]

    # THIS FLIGHT — only if we have anything to show.
    sess = dict(session or {})
    sess.update({k: v for k, v in extras.items() if v is not None})
    if sess:
        out.append("  THIS FLIGHT")
        auto = sess.get("auto_resolved")
        asked = sess.get("asked")
        rate = sess.get("autonomy_rate")
        if rate is None and auto is not None and asked is not None and (auto + asked):
            rate = auto / (auto + asked)
        line1 = []
        if auto is not None:
            line1.append(f"⚡ {auto} decided as you")
        if asked is not None:
            line1.append(f"🛡 {asked} paged you")
        if rate is not None:
            line1.append(f"→ {rate:.0%} autonomy")
        if line1:
            out.append("    " + "      ".join(line1))
        line2 = []
        gained = sess.get("precedents_gained")
        if gained:
            line2.append(f"🧠 +{gained} precedents learned")
        if sess.get("checks_green") is not None:
            line2.append(f"✓ {sess['checks_green']} checks green")
        if sess.get("commits"):
            line2.append(f"⬆ {sess['commits']} commits shipped")
        if line2:
            out.append("    " + "      ".join(line2))
        out.append("")

    # YOUR CLONE — all time.
    c = cumulative or {}
    out.append("  YOUR CLONE — all time")
    if c.get("episodes"):
        out.append(f"    👁  {c['episodes']:,} decisions shadowed")
    row = []
    if c.get("decisions"):
        row.append(f"⚖️  {c['decisions']} explicit calls")
    row.append(f"📚 {c.get('precedents', 0)} learned precedents")
    out.append("    " + "      ".join(row))
    row2 = [f"🧭 {c.get('practices', 0)} declared practices"]
    if c.get("calibration_accuracy") is not None:
        row2.append(f"🎯 {c['calibration_accuracy']:.0%} judgment accuracy")
    if c.get("cost_spent_usd"):
        row2.append(f"💾 ${c['cost_spent_usd']:,.2f} tracked · {c.get('cost_calls', 0):,} calls")
    out.append("    " + "      ".join(row2))
    out.append("")

    # Decision DNA — how you actually decide.
    dna = c.get("dna") or {}
    if dna:
        peak = max(dna.values())
        out.append("  HOW YOU ACTUALLY DECIDE")
        for kind in sorted(dna, key=lambda k: dna[k], reverse=True):
            out.append(f"    {kind:<8} {_bar(dna[kind], peak)} {dna[kind]}")
        out.append("")

    out.append("  Read live from your local brain. Nothing left your machine.")
    out.append(rule)
    return "\n".join(out)
