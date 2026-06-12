"""Autonomy Receipt — what the loop did, as you, on a given run.

After any operator run, this produces a human-readable receipt of every decision:
who decided (the clone vs you vs the gate), the confidence, and the rationale,
plus the headline number — the **autonomy rate** (steps resolved without paging
you / all decision points). It's the proof the loop ran as you.

Pure read-over-store, deterministic, no model needed.
"""
from __future__ import annotations

import json
from typing import Any


def _loads(val: Any) -> Any:
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val) if val else {}
    except (TypeError, ValueError):
        return {}


def _step_record(event_payload: dict) -> dict:
    """One decided step → a receipt line. `decided_by` is 'clone' when the Clone
    Resolver answered it as you, else 'gate' (the profile gate cleared it).

    The persisted verdict is sometimes the full gate dict (rich: decision +
    confidence + reason + source) and sometimes just the decision string — handle
    both so receipts work over any run."""
    pl = _loads(event_payload)
    raw = pl.get("verdict")
    v = raw if isinstance(raw, dict) else {"decision": str(raw or "")}
    source = str(v.get("source", ""))
    return {
        "step": str(pl.get("step_text") or pl.get("step", ""))[:200],
        "decided_by": "clone" if source == "resolver" else "gate",
        "decision": v.get("decision", ""),
        "confidence": round(float(v.get("confidence", 0) or 0), 2),
        "rationale": (v.get("reason") or v.get("rationale") or "")[:300],
    }


def build_receipt(store: Any, run_ids: list[int]) -> dict:
    """Build a structured receipt over one or more runs. Never raises on a missing
    run — it's skipped. Returns {runs: [...], totals: {...}}."""
    runs: list[dict] = []
    tot_auto = tot_asked = 0

    for rid in run_ids:
        try:
            run = store.get_run(rid)
        except Exception:
            run = None
        if not run:
            continue

        goal = ""
        pid = run.get("plan_id")
        if pid:
            try:
                goal = (store.get_plan(pid) or {}).get("goal", "")
            except Exception:
                goal = ""

        # step_done events are newest-first → reverse to chronological.
        try:
            events = [e for e in store.get_run_events(rid) if e.get("type") == "step_done"]
        except Exception:
            events = []
        steps = [_step_record(e.get("payload", {})) for e in reversed(events)]

        try:
            escs = store.get_escalations(rid)
        except Exception:
            escs = []
        asks = []
        for esc in escs:
            ctx = _loads(esc.get("context"))
            decision = esc.get("user_decision")
            if not decision:
                decision = "(open — waiting on you)" if esc.get("status") == "open" else ""
            asks.append({
                "question": str(esc.get("question", ""))[:200],
                "decided_by": "human",
                "decision": decision,
                "clone_had_attempt": isinstance(ctx, dict) and "clone_attempt" in ctx,
            })

        auto, asked = len(steps), len(asks)
        tot_auto += auto
        tot_asked += asked
        runs.append({
            "run_id": rid,
            "goal": goal,
            "status": run.get("status", ""),
            "autonomy_level": run.get("autonomy_level", ""),
            "spent_usd": round(float(run.get("spent_usd", 0) or 0), 4),
            "steps": steps,
            "asks": asks,
            "auto_resolved": auto,
            "asked": asked,
            "autonomy_rate": (auto / (auto + asked)) if (auto + asked) else 1.0,
        })

    denom = tot_auto + tot_asked
    return {
        "runs": runs,
        "totals": {
            "auto_resolved": tot_auto,
            "asked": tot_asked,
            "autonomy_rate": (tot_auto / denom) if denom else 1.0,
        },
    }


def render_markdown(receipt: dict) -> str:
    """Render a receipt as a scannable markdown block."""
    out: list[str] = []
    for r in receipt.get("runs", []):
        out.append(f"## 🧾 Autonomy receipt — run #{r['run_id']}")
        if r.get("goal"):
            out.append(f"_{r['goal']}_")
        out.append(
            f"status **{r['status']}** · autonomy **{r['autonomy_level']}** · "
            f"spent ${r['spent_usd']:.4f}"
        )
        out.append("")
        for i, s in enumerate(r["steps"], 1):
            who = "🤖 clone" if s["decided_by"] == "clone" else "🛡 gate"
            out.append(
                f"  {i}. {who} → **{s['decision']}** "
                f"(conf {s['confidence']:.0%}) — {s['rationale']}"
            )
        for a in r["asks"]:
            out.append(f"  ⏸ paged you: {a['question']} → {a['decision']}")
        out.append("")
        out.append(
            f"**Autonomy this run: {r['autonomy_rate']:.0%}** "
            f"— {r['auto_resolved']} resolved as you · {r['asked']} paged you"
        )
        out.append("")
    t = receipt.get("totals", {})
    if len(receipt.get("runs", [])) > 1:
        out.append(
            f"### Across {len(receipt['runs'])} runs: "
            f"**{t.get('autonomy_rate', 1.0):.0%} autonomy** "
            f"({t.get('auto_resolved', 0)} resolved · {t.get('asked', 0)} paged)"
        )
    return "\n".join(out).rstrip() + "\n"
