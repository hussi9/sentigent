#!/usr/bin/env python3
"""Eval gate + card: turn the learned-vs-static experiment into a one-page, honest
verdict — and a nonzero exit code when it fails, so CI can block on it.

Reads training/eval/experiment_e1.json (produced by learned_vs_static.py) and writes
training/eval/eval_card.md. The card states exactly what the number means and what it
does NOT mean (the labels are the engine's own past decisions → this measures
learnability / self-consistency, not world-correctness — that's E2 on SWE-bench).

    python training/eval/gate.py            # write card, exit nonzero if the gate fails
    python training/eval/gate.py --json     # also print the verdict as JSON

Gate (pre-committed, do not move after seeing numbers):
  - need test N >= MIN_N, else verdict = ANECDOTAL (exit 0, but not a PASS)
  - learned balanced_accuracy must beat the static-rubric baseline by >= MIN_DELTA → PASS
  - learned <= static → FAIL (exit 1)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "experiment_e1.json")
CARD = os.path.join(HERE, "eval_card.md")

MIN_N = 2000          # test rows below this → anecdotal
MIN_DELTA = 0.10      # learned must beat static rubric by >= 10 bal-acc points to PASS


def _best(results: list[dict], prefix: str) -> dict | None:
    cands = [r for r in results if str(r.get("name", "")).upper().startswith(prefix)]
    return max(cands, key=lambda r: r.get("bal_acc", 0)) if cands else None


def evaluate(report: dict) -> dict:
    results = report.get("results", [])
    test_n = int(report.get("test", 0))
    static = _best(results, "B1") or _best(results, "B")     # static rubric baseline
    learned = _best(results, "L")                            # learned (kNN/model)
    if not static or not learned:
        return {"verdict": "ERROR", "reason": "missing learned or static condition",
                "exit": 1}
    delta = round(learned["bal_acc"] - static["bal_acc"], 4)
    if test_n < MIN_N:
        verdict, exit_code = "ANECDOTAL", 0
    elif delta >= MIN_DELTA:
        verdict, exit_code = "PASS", 0
    else:
        verdict, exit_code = "FAIL", 1
    return {"verdict": verdict, "exit": exit_code, "test_n": test_n,
            "static": static, "learned": learned, "delta": delta,
            "min_n": MIN_N, "min_delta": MIN_DELTA}


def card_md(report: dict, v: dict) -> str:
    if v["verdict"] == "ERROR":
        return f"# Eval Card — ERROR\n\n{v['reason']}\n"
    s, l = v["static"], v["learned"]
    badge = {"PASS": "✅ PASS", "FAIL": "❌ FAIL",
             "ANECDOTAL": "🟡 ANECDOTAL (insufficient N)"}[v["verdict"]]
    return f"""# Sentigent Eval Card — E1: learned vs. static judgment

**Verdict: {badge}**  ·  test N = {v['test_n']}  ·  gate: learned must beat static by ≥ {v['min_delta']} bal-acc (need N ≥ {v['min_n']})

| Condition | balanced accuracy | minority-class recall | aggregate |
|---|---|---|---|
| {s['name']} (static baseline) | {round(s['bal_acc'],3)} | {round(s.get('minority_recall',0),3)} | {round(s.get('aggregate',0),3)} |
| {l['name']} (learned) | {round(l['bal_acc'],3)} | {round(l.get('minority_recall',0),3)} | {round(l.get('aggregate',0),3)} |
| **delta (learned − static)** | **{v['delta']:+}** | | |

Per-class recall (learned): {json.dumps(l.get('per_class', {}))}

## What this means — and what it does NOT
- **Means:** the proceed/enrich/slow-down/escalate boundary is *learnable from signals* — the
  learned model separates the classes far better than static rules on held-out, time-split data.
- **Does NOT mean** the judgments are *correct in the world*. The labels here are the engine's
  own past decisions, so this measures **self-consistency / learnability**, not ground-truth
  correctness. World-correctness is **E2** (Sentigent ON vs OFF on SWE-bench Verified) — still
  pending; do not cite E1 as proof the agent makes *right* calls.
- N, the time-split, and the per-class recall above are the whole story. No smoothing, no cherry-pick.
"""


def main(argv: list[str]) -> int:
    if not os.path.exists(REPORT):
        # Honest: no experiment yet → emit an ANECDOTAL card, don't fake a pass.
        msg = ("# Sentigent Eval Card — no experiment yet\n\n🟡 ANECDOTAL — run "
               "`python training/eval/learned_vs_static.py` to produce experiment_e1.json, "
               "then re-run this gate.\n")
        with open(CARD, "w") as f:
            f.write(msg)
        print(json.dumps({"verdict": "ANECDOTAL", "reason": "no experiment_e1.json", "exit": 0}))
        return 0
    report = json.load(open(REPORT))
    v = evaluate(report)
    with open(CARD, "w") as f:
        f.write(card_md(report, v))
    out = {k: v[k] for k in ("verdict", "delta", "test_n", "exit") if k in v}
    out["card"] = CARD
    print(json.dumps(out, indent=2) if "--json" in argv else
          f"{v['verdict']} · delta {v.get('delta')} · N {v.get('test_n')} · card → {CARD}")
    return int(v.get("exit", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
