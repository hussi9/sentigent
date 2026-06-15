#!/usr/bin/env python3
"""behave-like-me agreement harness — the honest "did the engine decide like the human?" test.

The ONLY ground-truth signal for "behave like me" lives in answered escalations:
the human's `user_decision` is gold, and the engine's call is `context.verdict.decision`
(fallback `context.trigger`). Everything else (episodes) is engine-graded-by-outcome,
which measures *competence*, not *agreement with the human*. So we score agreement over
those gold pairs only — and we are loud about how few there are.

Honest caveats baked in:
  • N is tiny (~11 today). Below 50 the number is anecdotal, not significant — we say so.
  • Aggregate accuracy is gameable on a proceed-heavy distribution; balanced accuracy is
    the honest number. We print both, plus the constant-"proceed" baseline for contrast.
  • Episode decision distribution is shown to expose the class imbalance that makes
    aggregate misleading.

No GPU, no network. Pure read of local SQLite. Run:
  python training/eval_agreement.py --agent hussain
"""
from __future__ import annotations

import argparse, json, sqlite3, sys
from collections import Counter
from pathlib import Path

# import score() from the eval harness (per-class balanced accuracy + confusion)
sys.path.insert(0, str(Path(__file__).parent / "eval"))
from harness import score  # noqa: E402

SIG_THRESHOLD = 50  # below this, agreement rate is anecdotal not significant

# ── Label vocabulary normalization ────────────────────────────────────────────
# The two sides speak different vocabularies and comparing them raw is structurally
# zero (an honest bug found on first run, not a real disagreement):
#   • engine  records verdict.decision / trigger: escalate, continue, correct,
#     verify_failed, proceed, slow_down, enrich, ...
#   • human   records user_decision on an escalation: approve, takeover, skip, ...
# Every gold row is an escalation the engine RAISED, so the meaningful question is
# not "same label?" but "was raising it WARRANTED?" — i.e. escalation precision.
# We map both onto a shared axis {escalate, proceed} so score() is comparable and
# the headline number (precision) is honest.
WARRANTED = {"approve", "approved", "takeover", "take_over", "yes", "accept",
             "continue", "correct", "escalate", "confirm"}
UNWARRANTED = {"skip", "skipped", "reject", "rejected", "no", "abort", "ignore",
               "dismiss", "proceed", "continue_anyway"}


def _canon_human(h: str) -> str:
    """Human answer → was the escalation warranted? escalate=warranted, proceed=false-alarm."""
    h = (h or "").strip().lower()
    if h in WARRANTED:
        return "escalate"
    if h in UNWARRANTED:
        return "proceed"
    return "escalate"  # unknown human verb on an escalation → treat as warranted (conservative)


def _load(v: str) -> dict:
    try:
        return json.loads(v) if v else {}
    except Exception:
        return {}


def gold_pairs(conn) -> list[tuple[str, str]]:
    """Answered escalations → (engine_decision_raw, human_decision_raw). The only true signal."""
    try:
        rows = conn.execute(
            "SELECT context, user_decision FROM escalations "
            "WHERE status='answered' AND user_decision IS NOT NULL AND user_decision!=''"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  ⚠️  escalations table unavailable ({e}) — no gold signal.")
        return []
    pairs = []
    for context, human in rows:
        ctx = _load(context)
        engine = (ctx.get("verdict") or {}).get("decision") or ctx.get("trigger") or "escalate"
        pairs.append((engine, human))  # raw (engine, human)
    return pairs


def normalized_pairs(raw: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Map raw (engine, human) onto the shared {escalate, proceed} axis for score().

    The engine RAISED every gold row, so predicted='escalate' always; truth is whether
    the human deemed it warranted. balanced_accuracy on this == escalation precision.
    """
    return [("escalate", _canon_human(h)) for _engine, h in raw]


def escalation_precision(raw: list[tuple[str, str]]) -> tuple[float, Counter]:
    """Fraction of raised escalations the human deemed warranted (not a false alarm)."""
    verdicts = Counter(_canon_human(h) for _e, h in raw)
    total = sum(verdicts.values())
    warranted = verdicts.get("escalate", 0)
    return (warranted / total if total else 0.0), verdicts


def episode_distribution(conn, agent: str) -> dict:
    """Decision distribution over episodes — exposes the proceed-heavy imbalance."""
    try:
        rows = conn.execute(
            "SELECT decision, COUNT(*) FROM episodes WHERE agent_id=? AND decision!='' "
            "GROUP BY decision", (agent,),
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  ⚠️  episodes table unavailable ({e}) — skipping distribution.")
        return {}
    return dict(rows)


def baseline_constant(pairs: list[tuple[str, str]], const: str = "proceed") -> dict:
    """What a brain-dead constant predictor would score on the same gold labels."""
    return score([(const, true) for _, true in pairs])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="hussain")
    ap.add_argument("--db", default=str(Path.home() / ".sentigent"))
    args = ap.parse_args()

    db_path = Path(args.db) / f"memory_{args.agent}.db"
    if not db_path.exists():
        raise SystemExit(f"no brain at {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    raw = gold_pairs(conn)
    n = len(raw)

    print("━" * 64)
    print("  AGREEMENT — was the engine's escalation warranted by the human? (gold HITL)")
    print("━" * 64)
    print(f"  agent              : {args.agent}")
    print(f"  N (answered escalations w/ human label) : {n}")

    if n == 0:
        print("\n  🔴 zero gold pairs — cannot measure agreement. Answer some escalations.")
        sys.exit(1)

    # Honest headline: escalation precision (warranted rate) — engine/human vocabularies
    # are disjoint, so we score on the shared {escalate,proceed} axis instead of raw labels.
    prec, verdicts = escalation_precision(raw)
    pairs = normalized_pairs(raw)
    s = score(pairs)
    print(f"\n  escalation_precision : {round(prec,3)}   ← warranted / raised (the honest headline)")
    print(f"  human verdicts       : warranted={verdicts.get('escalate',0)} "
          f"false_alarm={verdicts.get('proceed',0)}")
    print(f"  balanced_accuracy    : {s['balanced_accuracy']}   (on shared escalate/proceed axis)")
    print(f"  per_class_recall     : {s['per_class_recall']}")
    print("\n  raw label confusion (engine_raw → human_raw → count) — shows the vocab gap:")
    raw_conf = Counter((e, h) for e, h in raw)
    for (e, h), c in sorted(raw_conf.items(), key=lambda kv: -kv[1]):
        print(f"    {e:<14} → {h:<12} ×{c}")

    base = baseline_constant(pairs)
    print(f"\n  baseline (constant 'proceed'): aggregate={base['aggregate_accuracy']} "
          f"balanced={base['balanced_accuracy']}")

    if n < SIG_THRESHOLD:
        print(f"\n  ⚠️  WARNING: N={n} < {SIG_THRESHOLD}. This agreement rate is ANECDOTAL, "
              f"not statistically significant.")
        print("      Treat it as a smoke signal, not a benchmark. Do NOT report it as 'accuracy'.")
        print("      Note: engine labels (verdict.decision/trigger) and human labels live in")
        print("      different vocabularies, so low overlap is expected — that's an honest finding.")

    dist = episode_distribution(conn, args.agent)
    if dist:
        total = sum(dist.values())
        top = max(dist, key=dist.get)
        share = dist[top] / total if total else 0.0
        print("\n" + "━" * 64)
        print("  EPISODE DECISION DISTRIBUTION — why aggregate is misleading")
        print("━" * 64)
        for d, c in sorted(dist.items(), key=lambda kv: -kv[1]):
            print(f"    {d:<12} {c:>8}  ({c/total:.1%})")
        print(f"\n  '{top}' is {share:.1%} of all decisions → a constant predictor looks great")
        print("  on aggregate while learning nothing. Balanced accuracy resists this.")

    sys.exit(0)


if __name__ == "__main__":
    main()
