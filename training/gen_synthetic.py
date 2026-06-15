#!/usr/bin/env python3
"""Synthetic-data generator — teacher proposes, the oracle gate disposes.

Pipeline (all local except the teacher call):

  compose(packs) → for each rule:
      teacher emits N candidate trajectories (JSON)  →  run each through the
      rule's ORACLE (the SAME gate the eval harness validated as discriminating)
      →  keep only oracle-PASSING rows  →  write SFT to data/synth/<rule>.jsonl
  → per-rule drop-rate log + data/synth/_summary.json

Why a gate: the teacher is a noisy oracle. A candidate is only kept if the rule's
content-inspecting oracle (actions order / signals / diff — never the label) passes
it. That makes the dataset self-cleaning: junk the teacher hallucinates is dropped.

ALARMS on drop_rate:
  < 0.20 → gate too weak OR teacher trivially gaming it (suspiciously clean).
  > 0.70 → rubric/teacher mismatch (teacher can't satisfy the rule).

Output format (one JSON object per line) — SFT triples + the raw trajectory kept
for re-gating / debugging:
  {"messages": [ {role:system}, {role:user}, {role:assistant} ], "rule_id", "trajectory"}

Run:
  python training/gen_synthetic.py --dry-run                # zero-cost, stub teacher
  python training/gen_synthetic.py --n 8 --packs tdd        # real teacher
  CLAUDE_BIN=claude python training/gen_synthetic.py --n 4
"""
from __future__ import annotations

import argparse, json, os, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("pip install pyyaml")

HERE = Path(__file__).parent
EVAL = HERE / "eval"
OUT = HERE / "data" / "synth"
CLAUDE = os.environ.get("CLAUDE_BIN") or "claude"

# Reuse the harness's validated, discriminating gate — single source of truth.
sys.path.insert(0, str(EVAL))
from harness import ORACLES  # noqa: E402

from compose import compose  # noqa: E402

ALARM_LOW, ALARM_HIGH = 0.20, 0.70
SYSTEM = ("You are Sentigent's judgment layer. Emit a trajectory: a decision "
          "(proceed|enrich|slow_down|escalate), the signals you observed, the ordered "
          "actions you took, an optional diff, and a one-line reason.")


# ── teacher ───────────────────────────────────────────────────────────────────

def _teacher_prompt(rule: dict, n: int) -> str:
    return (
        f"Produce {n} DISTINCT candidate trajectories for this engineering-judgment rule.\n\n"
        f"rule_id : {rule['id']}\n"
        f"when    : {rule.get('when', '')}\n"
        f"rule    : {rule.get('principle') or rule.get('situation') or ''}\n"
        f"intent  : {rule.get('intent', [])}\n"
        f"decision: {rule.get('decision', '')}\n"
        f"severity: {rule.get('severity', '')}\n\n"
        "Each trajectory is an object: "
        '{"decision","signals":{},"actions":[],"diff":"","reason":""}. '
        "Make them realistic and varied (different files/signals). "
        "Reply with ONLY a JSON array of the trajectory objects, no prose."
    )


def teacher_call(rule: dict, n: int, timeout: float = 180.0) -> list[dict]:
    """Ask the teacher for N candidate trajectories. Tolerant of claude -p's event list."""
    cmd = [CLAUDE, "-p", _teacher_prompt(rule, n), "--output-format", "json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    try:
        j = json.loads(p.stdout)
    except Exception:
        return []
    # `claude -p --output-format json` returns a LIST of events; the final {type:"result"}
    # carries the answer text. Be tolerant of dict-or-list.
    if isinstance(j, list):
        j = next((x for x in reversed(j) if isinstance(x, dict) and x.get("type") == "result"), {})
    text = j.get("result", "") if isinstance(j, dict) else (p.stdout or "")
    return _parse_candidates(text)


def _parse_candidates(text: str) -> list[dict]:
    """Extract the JSON array of trajectory objects from teacher text (fenced or bare)."""
    s = (text or "").strip()
    if "```" in s:  # strip a ```json … ``` fence if present
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s
        s = s[4:].strip() if s.lower().startswith("json") else s
    i, jx = s.find("["), s.rfind("]")
    if i < 0 or jx <= i:
        return []
    try:
        arr = json.loads(s[i : jx + 1])
    except Exception:
        return []
    return [c for c in arr if isinstance(c, dict)]


# ── deterministic stub teacher (dry-run) ───────────────────────────────────────

def _fixtures() -> dict[str, dict]:
    """rule_id -> {good, bad} from the eval fixtures (known-discriminating examples)."""
    fx = (yaml.safe_load((EVAL / "fixtures.yaml").read_text()) or {}).get("fixtures", [])
    ext = EVAL / "fixtures_ext.yaml"
    if ext.exists():
        fx += (yaml.safe_load(ext.read_text()) or {}).get("fixtures", [])
    return {f["rule_id"]: f for f in fx}


def stub_teacher(rule: dict, n: int, _fx: dict) -> list[dict]:
    """Zero-network teacher: return one oracle-passing + one oracle-failing candidate
    (sourced from the eval fixtures), padded to n. Proves the gate keeps good, drops bad."""
    f = _fx.get(rule["id"])
    if not f:
        return []
    good, bad = f["good"], f["bad"]
    out = [good, bad]
    while len(out) < n:  # deterministic padding: alternate good/bad
        out.append(good if len(out) % 2 == 0 else bad)
    return out[:n]


# ── SFT row ────────────────────────────────────────────────────────────────────

def _sft_row(rule: dict, traj: dict) -> dict:
    user = (f"Situation ({rule['id']}): {rule.get('when', '')}\n"
            f"Signals: {json.dumps(traj.get('signals', {}), sort_keys=True)}\n"
            "What do you do?")
    assistant = json.dumps({
        "decision": traj.get("decision"),
        "actions": traj.get("actions", []),
        "reason": traj.get("reason", ""),
    }, sort_keys=True)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "rule_id": rule["id"],
        "trajectory": traj,
    }


# ── generate ───────────────────────────────────────────────────────────────────

def generate(rules: list[dict], n: int, dry_run: bool) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    fx = _fixtures() if dry_run else {}
    per_rule, total_cand, total_kept = [], 0, 0
    alarms = []

    for rule in rules:
        rid = rule["id"]
        oracle = ORACLES.get(rid)
        if not oracle:  # ungated rules can't be quality-checked → skip, don't pollute
            per_rule.append({"rule": rid, "status": "NO_ORACLE", "candidates": 0, "kept": 0})
            continue

        cands = stub_teacher(rule, n, fx) if dry_run else teacher_call(rule, n)
        kept = [c for c in cands if _safe_oracle(oracle, c)]
        total_cand += len(cands)
        total_kept += len(kept)

        path = OUT / f"{rid}.jsonl"
        path.write_text("".join(json.dumps(_sft_row(rule, c)) + "\n" for c in kept))

        drop = round(1 - len(kept) / len(cands), 3) if cands else None
        row = {"rule": rid, "candidates": len(cands), "kept": len(kept), "drop_rate": drop}
        if drop is not None and len(cands) >= 2:  # alarm only with a meaningful sample
            if drop < ALARM_LOW:
                row["alarm"] = "DROP_TOO_LOW (gate weak / teacher gaming)"
                alarms.append(row["rule"])
            elif drop > ALARM_HIGH:
                row["alarm"] = "DROP_TOO_HIGH (teacher/rubric mismatch)"
                alarms.append(row["rule"])
        per_rule.append(row)

    gated = [r for r in per_rule if r.get("status") != "NO_ORACLE"]
    overall_drop = round(1 - total_kept / total_cand, 3) if total_cand else None
    return {
        "mode": "dry-run" if dry_run else "live",
        "n_per_rule": n,
        "rules_total": len(rules),
        "rules_gated": len(gated),
        "rules_no_oracle": len(per_rule) - len(gated),
        "candidates": total_cand,
        "kept": total_kept,
        "overall_drop_rate": overall_drop,
        "alarms": alarms,
        "per_rule": per_rule,
    }


def _safe_oracle(oracle, cand: dict) -> bool:
    try:
        return oracle(cand) is True
    except Exception:
        return False  # a candidate that crashes the oracle is not verified → drop


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packs", nargs="*", default=[], help="opt-in practice packs")
    ap.add_argument("--n", type=int, default=6, help="candidate trajectories per rule")
    ap.add_argument("--dry-run", action="store_true", help="stub teacher, zero API cost")
    args = ap.parse_args()

    eff = compose(args.packs)
    summary = generate(eff["rules"], args.n, args.dry_run)
    (OUT / "_summary.json").write_text(json.dumps(summary, indent=2))

    print("━" * 64)
    print(f"  SYNTHETIC GEN — {summary['mode']}  (n={args.n}/rule, packs={args.packs or '∅'})")
    print("━" * 64)
    for r in summary["per_rule"]:
        if r.get("status") == "NO_ORACLE":
            print(f"  ⚠️  {r['rule']:<32} NO ORACLE — skipped")
            continue
        if r["candidates"] == 0:
            print(f"  ∅  {r['rule']:<32} teacher returned 0 candidates")
            continue
        mark = "🔔" if r.get("alarm") else "✅"
        print(f"  {mark} {r['rule']:<32} cand={r['candidates']:>2} kept={r['kept']:>2} "
              f"drop={r['drop_rate']}" + (f"  {r['alarm']}" if r.get("alarm") else ""))
    print("─" * 64)
    print(f"  gated rules : {summary['rules_gated']}  (no-oracle: {summary['rules_no_oracle']})")
    print(f"  candidates  : {summary['candidates']}   kept: {summary['kept']}   "
          f"overall_drop: {summary['overall_drop_rate']}")
    if summary["alarms"]:
        print(f"  🔔 ALARMS   : {summary['alarms']}")
    print(f"\nsaved → {OUT}/<rule>.jsonl  +  {OUT/'_summary.json'}")


if __name__ == "__main__":
    main()
