# Sentigent is a Data-First project

The durable asset is **the dataset**, not the model. Models commoditize; the curated
best-practice rubric + the synthetic corpus built from it + your live preference
stream are proprietary and compounding. The model is a late, swappable consumer of
this data. Build the data once; pick/retrain the model whenever.

The same dataset powers all three "behave-like-me" mechanisms:
- **retrieval** (works today, no training),
- **prompt-steering** (today — the Learned Steering File),
- **SFT / DPO** (later, when D2/D3 are big enough).

So we are never blocked on "do we fine-tune." We build data; model choice is reversible.

---

## The three datasets (the product)

### D1 — Rubric  (`best_practices.yaml`)
Versioned, **verifiable** best-practice rules. The "constitution". Each rule:
`{situation → ideal_sequence → skills/tools → decision → reason → verify}`. Hand-curated.

### D2 — Synthetic corpus  (`data/sft.jsonl`)
Claude-Code/Codex-specific trajectories **generated from D1** by a teacher model,
then **quality-gated** (every example must pass its rule's `verify` / a judge before
it enters). Fixes the data-poverty problem (we have only 6 real `escalate` examples).
SFT fuel = the best-practice floor.

### D3 — Preference stream  (`data/preference.jsonl`)
Your **live** overrides + answered escalations. `(chosen = your call, rejected =
engine's call)`. The personalization / RLHF fuel — the only true "behave-like-me"
signal. Tiny today (11 pairs); grows every time you correct the agent.

> **SFT on D2 = competent senior-dev floor. DPO/RLHF on D3 = personalized to you.**
> D1 generates D2. Using the product generates D3.

---

## The data flywheel

```
USE → log decision+outcome → LABEL (verifier = auto, you = HITL gold)
    → CURATE (dedup · balance · provenance) → find coverage gaps
    → SYNTHESIZE from rubric to fill gaps → retrain / re-steer → USE …
```

Each turn improves the *dataset*, which improves *any* model. The `SIGNALS.md`
leading metrics (precedent-reuse ↑, override-rate ↓) are data-quality metrics.

---

## Data-first disciplines (non-negotiable)

1. **Typed examples + provenance.** Every record:
   `{input, output, label_source: rubric|verifier|human, rule_id?, confidence, dataset_version}`.
   No anonymous data — we must always know *where a label came from*.
2. **Versioned datasets** (`dataset-v1`, `v2` …). Eval is pinned to a version.
3. **Quality gate is mandatory.** Nothing enters D2 without passing `verify`/judge.
   Dropped examples are logged (publish the drop rate).
4. **Held-out eval set** = your real decisions, never trained on → measures
   **agreement rate** (the "like-me" number) and **VACR**.
5. **Class balance is a data defect, not a model problem.** Today: proceed 76,995 /
   enrich 800 / slow_down 235 / **escalate 6**. Synthesis exists to fix this.
6. **The model is the last step, and it's swappable.**

---

## Status (real, today)

- D1: seeded — 7 verifiable rules in `best_practices.yaml`.
- D2: `build_dataset.py` extracts 3,441 balanced SFT records from the brain, but
  rare classes are starved (escalate=6) → **needs synthetic generation next.**
- D3: 11 preference pairs, all real human-vs-engine disagreements.

## Build order (data-first)

1. **Synthetic generator + quality gate** — D1 → D2, balanced, every example verified.
2. **Held-out eval set** — agreement-rate harness (the "like-me" metric).
3. **Retrieval + steering** consume D2/D3 now (no training) — usable immediately.
4. **LoRA SFT (D2) → DPO (D3)** — only once volumes clear the bar. Kill-gated.
5. **Live flywheel** — overrides auto-append to D3; gaps auto-trigger synthesis.
