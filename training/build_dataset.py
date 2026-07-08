#!/usr/bin/env python3
"""Turn the Sentigent brain into real training data — offline learning step 1.

Reads ~/.sentigent/memory_<agent>.db and emits three artifacts:

  1. sft.jsonl        — supervised set: "competent decision behavior".
                        input = (action + context + signals), output = {decision, reason}.
                        Honest label note: these decisions were made by the CURRENT
                        engine, graded by OUTCOME. So SFT here teaches *competent default
                        behaviour*, NOT "behave like Hussain". The "like-me" bend comes
                        from the preference set below.
  2. preference.jsonl — DPO/RLHF set from HITL gold (answered escalations): when the
                        human's `user_decision` differs from the engine's verdict, that
                        is a real (chosen=human, rejected=engine) pair. THIS is the
                        "behave like me" signal. Tiny today (that's the finding).
  3. stats.json       — class balance + the imbalance problem, quantified.

Class imbalance is the silent killer (≈96% "proceed"), so the SFT set is emitted
both RAW and BALANCED (proceed capped at `--cap-ratio`× the next-largest class).

No GPU, no network. Pure read of local SQLite. Run:
  python training/build_dataset.py --agent hussain
"""
from __future__ import annotations

import argparse, json, os, sqlite3
from collections import Counter
from pathlib import Path

SYSTEM = (
    "You are the operator's judgment layer. Given an action the agent is about to take, "
    "its context and risk signals, decide one of: proceed, enrich, slow_down, escalate. "
    "Reply as JSON: {\"decision\": <action>, \"reason\": <one line>}."
)


def _load(v: str) -> dict:
    try:
        return json.loads(v) if v else {}
    except Exception:
        return {}


def _user_prompt(task: str, context: dict, signals: dict) -> str:
    ctx = {k: context.get(k) for k in list(context)[:8]} if isinstance(context, dict) else {}
    sig = {k: signals.get(k) for k in list(signals)[:8]} if isinstance(signals, dict) else {}
    return (
        f"ACTION:\n{task}\n\nCONTEXT:\n{json.dumps(ctx, default=str)[:800]}\n\n"
        f"SIGNALS:\n{json.dumps(sig, default=str)[:400]}"
    )


def build_sft(conn, agent: str) -> list[dict]:
    """Episodes with an informative outcome → SFT records. Skip neutral/unlabeled."""
    rows = conn.execute(
        "SELECT task, context, signals, decision, reason, outcome "
        "FROM episodes WHERE agent_id=? AND decision!='' AND outcome IN ('correct','incorrect')",
        (agent,),
    ).fetchall()
    out = []
    for task, context, signals, decision, reason, outcome in rows:
        # Only learn from decisions that led to a GOOD outcome (correct). An
        # 'incorrect' outcome means the decision was wrong — keep it OUT of the
        # imitation target (it would teach the mistake). It belongs in analysis.
        if outcome != "correct":
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _user_prompt(task, _load(context), _load(signals))},
                {"role": "assistant",
                 "content": json.dumps({"decision": decision, "reason": (reason or "")[:200]})},
            ],
            "_decision": decision,
        })
    return out


def balance(records: list[dict], cap_ratio: float) -> list[dict]:
    """Cap the dominant class so the learner can't collapse to 'always proceed'."""
    by = Counter(r["_decision"] for r in records)
    if not by:
        return records
    rare = sorted(by.values())
    second = rare[-2] if len(rare) > 1 else rare[-1]
    cap = max(int(second * cap_ratio), 50)
    kept, seen = [], Counter()
    for r in records:
        d = r["_decision"]
        if d == "proceed" and seen[d] >= cap:
            continue
        seen[d] += 1
        kept.append(r)
    return kept


def build_preference(conn) -> list[dict]:
    """Answered escalations → preference pairs. The HITL gold ('behave like me')."""
    rows = conn.execute(
        "SELECT question, context, user_decision FROM escalations "
        "WHERE status='answered' AND user_decision IS NOT NULL AND user_decision!=''"
    ).fetchall()
    pairs = []
    for question, context, user_decision in rows:
        ctx = _load(context)
        engine = (ctx.get("verdict") or {}).get("decision") or ctx.get("trigger") or "escalate"
        prompt = f"BLOCKER:\n{question}\n\nCONTEXT:\n{json.dumps(ctx, default=str)[:600]}"
        chosen = json.dumps({"decision": user_decision})
        rejected = json.dumps({"decision": engine})
        pairs.append({
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "_agree": user_decision == engine,
        })
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="default_agent")
    ap.add_argument("--db", default=str(Path.home() / ".sentigent"))
    ap.add_argument("--out", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--cap-ratio", type=float, default=3.0)
    args = ap.parse_args()

    db_path = Path(args.db) / f"memory_{args.agent}.db"
    conn = sqlite3.connect(db_path)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    sft_raw = build_sft(conn, args.agent)
    sft_bal = balance(sft_raw, args.cap_ratio)
    pref = build_preference(conn)

    def dump(name, recs, drop=("_decision", "_agree")):
        with open(outdir / name, "w") as f:
            for r in recs:
                f.write(json.dumps({k: v for k, v in r.items() if k not in drop}) + "\n")

    dump("sft.jsonl", sft_bal)
    dump("sft_raw.jsonl", sft_raw)
    dump("preference.jsonl", pref)

    stats = {
        "agent": args.agent,
        "sft_raw": len(sft_raw),
        "sft_balanced": len(sft_bal),
        "sft_class_raw": dict(Counter(r["_decision"] for r in sft_raw)),
        "sft_class_balanced": dict(Counter(r["_decision"] for r in sft_bal)),
        "preference_pairs": len(pref),
        "preference_real_disagreements": sum(1 for p in pref if not p["_agree"]),
        "verdict": _verdict(sft_bal, pref),
    }
    with open(outdir / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


def _verdict(sft, pref) -> str:
    rare = sum(1 for r in sft if r["_decision"] in ("escalate", "slow_down"))
    real_pref = sum(1 for p in pref if not p["_agree"])
    if rare < 50:
        return (f"NOT-READY for SFT: only {rare} rare-class (escalate/slow_down) examples. "
                f"Need synthetic augmentation. Real preference pairs: {real_pref} "
                f"(need ~hundreds for DPO). Use retrieval+steering now; fine-tune later.")
    return f"SFT viable ({len(sft)} balanced). Preference pairs: {real_pref}."


if __name__ == "__main__":
    main()
