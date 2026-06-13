# Proof — what Sentigent actually does, in numbers

No modeled counterfactuals, no vibes. Every number here is read from a live brain
or a real A/B you can re-run. (Policy: `docs/DECISIONS.md` D-008 / D-010.)

## Receipt 1 — it's not a logger, it's a judge (live brain, one real user)

Pulled from a production `~/.sentigent` brain via `sentigent_score()` / `sentigent_insights()`:

| Metric | Value |
| --- | --- |
| Decisions judged (lifetime) | **89,523** |
| Active interventions (not "proceed") | **3,495** — 3,176 enrich · 280 slow-down · 39 escalate |
| Per-tool correctness | Bash 1098/1098 · Edit 245/245 · Write 110/110 · Agent 26/26 |
| Calibration (Brier score) | **0.039 → "well-calibrated"** |

The point isn't the raw count — it's that **~4% of actions got a non-trivial
judgment** (gather more context, slow down, or stop and ask). A rubber stamp
would show 0. Sentigent doesn't.

## Receipt 2 — verify + self-repair beats one-shot (HumanEval A/B)

Same base model, same tasks, **Sentigent ON vs OFF**:

- **OFF** — blank `claude -p`, one shot, graded on the official hidden test.
- **ON** — generate → run the task's own tests (Sentigent's Verifier) → on
  failure, self-repair with the error fed back (≤3 attempts). Graded on the
  *same* hidden test. ON never sees the grader.

So the delta is the **verify+repair mechanism**, not model smartness.

```
SENTIGENT EVAL CARD — HumanEval A/B (N=164, same base model both arms)

  metric                          OFF (blank)   ON (Sentigent)
  verified pass@1                  159 (97%)      164 (100%)
  failures (= human-fix events)        5              0
  auto-self-repaired (no human)        —              6
  ON failures                          —              0   (passed every task)

  Δ verified pass@1 : +3 points
  Δ failures        : -5   (5 fewer tasks a human would have had to fix)
```

**Read it honestly.** The base model already aces 97% of HumanEval — there's
little headroom, so the *raw* delta is small (+3 points). The real result is the
**failure column: 5 → 0.** Every task the base model got wrong on the first try,
the verify→self-repair loop recovered with **zero human intervention**, and ON
failed nothing. That's the claim — "it cleans up the model's misses unattended" —
at its true size: valuable on the slice that fails, modest in aggregate on an
already-saturated benchmark.

Two of the six repairs (HumanEval/46, /83) were cases where ON's *own* test run
flagged a problem its first attempt missed and it self-corrected — the loop
firing as designed, not a hidden-test win over OFF.

**Honest caveat:** token cost is *not* cleanly measurable through `claude -p`
(~22k tokens of harness overhead per call swamp the task tokens). We report
correctness + intervention deltas; we do **not** claim a token-savings number
from this harness.

## How to re-run it yourself

```bash
python eval/humaneval_ab.py --n 164 --max-attempts 3
# → eval/results/humaneval_ab_full.json  (+ printed Eval Card)
sentigent_score()      # the live-brain receipts above
sentigent_insights()   # per-tool correctness + Brier
```

## The one-liner (for conversation)

> Same model, same tasks. Sentigent doesn't make Claude smarter — it makes it
> **finish more without you**: run the tests before claiming done, fix its own
> failures, and stop to ask only when it should. The proof is a re-runnable A/B,
> not a pitch deck.
