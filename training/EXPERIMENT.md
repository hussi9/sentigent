# Experiment E1 — Does learned judgment beat a static rubric?

**Status:** the decisive precondition. Static, hand-written policy is now a commodity
(Databricks Omnigent ships it with distribution). Sentigent's *only* defensible moat is
that it **learns** judgment from your decisions. This experiment tests that claim cheaply,
offline, on real data — before spending a cent on SWE-bench.

## Hypothesis

> H1: A predictor that **learns from the operator's decision history** (retrieval / kNN over
> past episodes) predicts held-out decisions with **higher balanced accuracy** than a
> **static rubric** (fixed thresholds on signals) — especially on the minority classes
> (enrich / slow_down / escalate) that actually matter.

Null (H0): learning does not beat the static rubric on held-out data. If H0 holds, the
"it learns" claim is unsupported **on the current data** → do NOT spend on SWE-bench; either
manufacture a learnable corpus (the synthetic generator) or drop the learning claim and
compete as "best local, personal baseline rubric + escalation gate."

## Why balanced accuracy, not accuracy

The decision distribution is **96.1% proceed** (86,035 / 89,530). A constant "proceed"
predictor scores 0.96 aggregate and is useless — it never catches the 4% of moments that
need intervention. Balanced accuracy (mean per-class recall) and **minority-class recall**
are the honest lens: the whole value of a judgment layer is *correctly not-proceeding when
it shouldn't*.

## Conditions

| id | predictor | what it represents |
|----|-----------|--------------------|
| **B0** | constant `proceed` | the floor / sanity check |
| **B1** | static rubric — fixed thresholds on the 5 signals | hand-written policy (the Omnigent-style baseline) |
| **L1** | kNN over the signal vector | learning from *similar situations* (signals only) |
| **L2** | kNN over signals ⊕ TF-IDF(task text) | learning from situation + content |

B1 is the bar to beat. L1/L2 are "learning." L2−B1 is the headline.

## Data & split

- Source: `~/.sentigent/memory_<agent>.db` → `episodes` where `decision != ''`.
- Features: parsed `signals` (caution, doubt, urgency, confidence, frustration) + `task` text.
- Label: `decision` ∈ {proceed, enrich, slow_down, escalate}.
- **Time-ordered split** (train = earlier 80%, test = later 20%) — honest "does past predict
  future," not random leakage.

## Metric & decision rule

Report per condition: balanced accuracy, minority-class recall (mean over the 3 non-proceed
classes), aggregate accuracy, confusion.

- **PASS (learning has a real edge):** `bal_acc(best learned) − bal_acc(B1) ≥ +0.05`
  AND minority recall improves. → justifies SWE-bench spend.
- **MARGINAL:** improvement < 0.05. → corpus is too weak; generate synthetic, re-run.
- **FAIL:** learned ≤ B1. → learning unproven on this data; reposition honestly.

## Threats to validity

- Signals are emotion/uncertainty proxies, not ground-truth risk — both conditions share
  this limit, so the *comparison* is still fair.
- Labels are the engine's own past decisions, not human-verified — this measures
  "learnable self-consistency," not correctness. A stronger follow-up uses HITL labels
  (only 11 today). Stated, not hidden.
- kNN is a deliberately simple learner; if even kNN beats the rubric, a trained model can
  only do better. If kNN can't, that's a strong negative signal.

Run: `.venv/bin/python3 training/eval/learned_vs_static.py --agent hussain`

---

## RESULTS — E1 (2026-06-15, agent=hussain, n=86,629, train=40k, test=6k, time-split)

| condition | bal_acc | minority_recall | aggregate |
|-----------|--------:|----------------:|----------:|
| B0 constant-proceed | 0.250 | 0.000 | 0.978 |
| **B1 static-rubric** (bar) | 0.646 | 0.528 | 0.990 |
| L1 learned-kNN(signals) | 0.937 | 0.917 | 0.999 |
| **L2 learned-kNN(sig+text)** | **0.954** | **0.970** | 0.910 |

**Headline: best learned − static rubric = +0.309 balanced accuracy, +0.442 minority recall. VERDICT: PASS.**

### What this proves — and what it does NOT (read before citing)

✅ **Proves: the decision boundary is LEARNABLE, and a learned model captures it far
better than a hand-written rubric.** This is exactly the Omnigent-relevant claim —
*learned policy > hand-written policy at making the right call*. The static rubric catches
`slow_down` 23% of the time; the learned model catches it 91%. Strong, necessary precondition.

⚠️ **Does NOT prove correctness.** Labels are the engine's *own past decisions*, which are
driven by these same signals — so kNN is partly reconstructing a decision function the crude
rubric only approximates. This measures **learnability / self-consistency**, not human-verified
correctness. A near-tautology guardrail: L1 (signals-only) hitting 0.94 confirms the signal→decision
map is highly recoverable; that's a feature-quality result, not a world-correctness result.

**Correctness ceiling still requires ground-truth labels** (human HITL = 11 today, or task
outcomes) → that is experiment **E2 (SWE-bench Verified, with/without the layer)**. E1 passing
is the green light for E2: don't spend on SWE-bench until the signal is known learnable. It is.
