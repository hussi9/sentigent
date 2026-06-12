#!/usr/bin/env python3
"""Gemma bake-off for the Clone Resolver (Loop plan T6.2).

Runs a small labeled set of blockers through gemma3:4b vs gemma3:27b and measures
(a) JSON validity, (b) agreement with the expected decision, (c) mean confidence on
correct calls. Picks the smallest model whose agreement clears the bar. Writes the
result to docs/superpowers/loop-cost-log.md.

Run: .venv/bin/python scripts/loop_gemma_bakeoff.py
Requires a local Ollama with gemma3:4b and gemma3:27b pulled.
"""
from __future__ import annotations

import time

from sentigent.intelligence import local_llm
from sentigent.operator.resolver import CloneResolver, NEEDS_HUMAN

PROFILE = {
    "summary": "Senior engineer. Ships fast, pragmatic. Tests before committing.",
    "preferences": ["small atomic commits", "TypeScript over JS", "real solutions over mocks"],
    "coding_standards": ["run the relevant tests before commit", "no hardcoded data"],
    "never_do": ["force-push main", "commit secrets", "delete files (move to .archive instead)"],
}

# (blocker step, category, precedents, expected decision)  — graded against Hussain's known prefs.
CASES = [
    ("regenerate the supabase types after the migration", "low_confidence",
     [{"blocker": "regen supabase types", "decision": "skip", "rationale": "I do it by hand"}], "skip"),
    ("run the test suite before committing the change", "low_confidence", [], "approve"),
    ("add a small atomic commit for the helper function", "low_confidence", [], "approve"),
    ("delete the old unused logo asset from the repo", "risk_ceiling", [], "needs_human"),
    ("hardcode the list of cities into the source file", "low_confidence", [], "skip"),
    ("write a mock data provider to fake the API in prod", "low_confidence", [], "skip"),
]

BAR = 0.66  # agreement threshold to be eligible


def run_model(model: str) -> dict:
    valid = correct = 0
    confs = []
    t0 = time.time()
    for step, cat, precs, expected in CASES:
        r = CloneResolver(PROFILE, model=model)
        res = r.resolve({"step_text": step, "category": cat, "trigger": cat,
                         "gate_reason": "low confidence", "risk_level": "normal"},
                        precedents=precs)
        if res.source == "llm":
            valid += 1
        # "agreement": exact, but treat a confident wrong as worse than needs_human.
        if res.decision == expected:
            correct += 1
            if res.decision != NEEDS_HUMAN:
                confs.append(res.confidence)
        print(f"  [{model}] {step[:48]:<48} → {res.decision:<11} "
              f"conf={res.confidence:.2f} (want {expected})")
    dt = time.time() - t0
    n = len(CASES)
    return {"model": model, "valid_json": valid / n, "agreement": correct / n,
            "mean_conf_correct": (sum(confs) / len(confs)) if confs else 0.0,
            "secs": round(dt, 1)}


def main() -> None:
    if not local_llm.llm_available():
        print("Ollama not reachable — start it and pull gemma3:4b / gemma3:27b.")
        return
    pulled = local_llm.list_models()
    candidates = [m for m in ("gemma3:4b", "gemma3:27b") if m in pulled]
    if not candidates:
        print(f"No gemma3 models pulled. Have: {pulled}")
        return

    results = []
    for m in candidates:
        print(f"\n=== {m} ===")
        results.append(run_model(m))

    eligible = [r for r in results if r["agreement"] >= BAR and r["valid_json"] >= 0.9]
    # smallest eligible model wins (candidates already ordered 4b before 27b)
    winner = eligible[0]["model"] if eligible else max(results, key=lambda r: r["agreement"])["model"]

    lines = ["# Sentigent Loop — Gemma bake-off (resolver model)\n",
             f"Bar: agreement ≥ {BAR}, valid_json ≥ 0.9. Cases: {len(CASES)}.\n",
             "| model | valid_json | agreement | mean_conf(correct) | secs |",
             "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['model']} | {r['valid_json']:.0%} | {r['agreement']:.0%} | "
                     f"{r['mean_conf_correct']:.2f} | {r['secs']} |")
    lines.append(f"\n**Winner: `{winner}`** → set `SENTIGENT_RESOLVER_MODEL={winner}`.")
    out = "\n".join(lines) + "\n"
    path = "docs/superpowers/loop-cost-log.md"
    with open(path, "w") as fh:
        fh.write(out)
    print("\n" + out)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
