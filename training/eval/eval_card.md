# Sentigent Eval Card — E1: learned vs. static judgment

**Verdict: ✅ PASS**  ·  test N = 6000  ·  gate: learned must beat static by ≥ 0.1 bal-acc (need N ≥ 2000)

| Condition | balanced accuracy | minority-class recall | aggregate |
|---|---|---|---|
| B1 static-rubric (static baseline) | 0.646 | 0.528 | 0.99 |
| L2 learned-kNN(sig+text) (learned) | 0.954 | 0.97 | 0.91 |
| **delta (learned − static)** | **+0.3087** | | |

Per-class recall (learned): {"proceed": 0.909, "enrich": 1.0, "slow_down": 0.909, "escalate": 1.0}

## What this means — and what it does NOT
- **Means:** the proceed/enrich/slow-down/escalate boundary is *learnable from signals* — the
  learned model separates the classes far better than static rules on held-out, time-split data.
- **Does NOT mean** the judgments are *correct in the world*. The labels here are the engine's
  own past decisions, so this measures **self-consistency / learnability**, not ground-truth
  correctness. World-correctness is **E2** (Sentigent ON vs OFF on SWE-bench Verified) — still
  pending; do not cite E1 as proof the agent makes *right* calls.
- N, the time-split, and the per-class recall above are the whole story. No smoothing, no cherry-pick.
