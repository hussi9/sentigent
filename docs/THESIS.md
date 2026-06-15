# Thesis: A Judgment Layer Improves Autonomous Reliability of a Coding Agent Without Changing the Base Model

*Research framing for Sentigent. Written to the standard a skeptical reviewer would
demand: falsifiable claims, attribution via ablation, honest threats to validity,
negative results published.*

---

## Abstract

Frontier coding agents fail not primarily from lack of capability but from
**unverified completion** — they report "done" without an oracle confirming it, and
they act autonomously on decisions that warrant a human. We introduce a **judgment
layer** that sits between an agent and its tools and adds three things the base model
lacks: (1) verification before "done", (2) bounded self-repair on failure, and (3)
calibrated escalation. We claim this does **not** raise model capability (pass@k under
unlimited human help) but raises **Verified Autonomous Completion Rate (VACR)** — tasks
finished *correctly AND with zero human intervention* — and that the gain is (a)
attributable to the verify+repair mechanism via ablation, (b) increasing in the base
model's first-shot failure rate, and (c) further improvable by personalization. We
report a preliminary HumanEval A/B (N=164) consistent with the claim on a saturated
benchmark, and pre-register the SWE-bench Verified study that would confirm or refute it.

---

## 1. Central thesis (one falsifiable sentence)

> Holding the base model fixed, a judgment layer increases **verified task completion
> per unit of human intervention**, and the increase is (i) caused by verify+repair
> (shown by ablation), (ii) monotonically larger as base first-shot accuracy drops, and
> (iii) further raised by personalization measured as per-class agreement with the user.

**Refutation conditions** (any one falsifies the corresponding clause):
- If ON ≤ OFF on VACR at equal human-intervention budget on a non-saturated benchmark → core claim false.
- If an ablation shows the gain persists with verify+repair *removed* → attribution false (something else explains it).
- If Δ VACR does not grow as base accuracy falls (HumanEval→MBPP→SWE-bench) → "headroom" claim false.
- If personalization adds ≤ noise to per-class balanced agreement → personalization claim false.

---

## 2. Hypotheses (decomposed, each independently testable)

- **H1 (Verification).** The layer reduces *false-done events* (claimed complete but
  failing hidden tests) vs the base agent. Metric: false-done rate.
- **H2 (Repair).** Bounded self-repair converts a measurable fraction of first-shot
  failures into zero-touch passes. Metric: recovery rate = repaired / first-shot-fails.
- **H3 (Headroom).** Δ VACR(ON−OFF) increases as base first-shot accuracy decreases.
  Metric: Δ VACR across three benchmarks of decreasing base accuracy.
- **H4 (Safety).** Escalation has high **recall** on irreversible/ambiguous actions
  (the dangerous false-negative) without unacceptable false-positive cost. Metric:
  escalation precision/recall on a labeled adversarial set.
- **H5 (Personalization).** Adding the user-preference signal raises per-class balanced
  agreement with the user vs baseline rules alone. Metric: balanced agreement, not aggregate.
- **H6 (No-capability-inflation, the honesty guardrail).** Under unlimited human help
  (pass@k with retries by a human), ON ≈ OFF. We explicitly predict **no** capability
  gain — the value is autonomy, not intelligence. (Stating a null we expect is itself
  anti-hype evidence.)

---

## 3. The intervention (what is being tested)

Base agent = `claude -p` (fixed weights). Treatment = the same agent wrapped by the
judgment pipeline: signals → risk/policy → decision {proceed, enrich, slow_down,
escalate} → Verifier (run the task's own oracle) → bounded self-repair → escalate.
The *only* difference between arms is the wrapper. Identical model, prompt budget, tools.

---

## 4. Experimental design

### 4.1 Baselines (a paper lives or dies on these)
- **B0 OFF** — blank one-shot generation (no verify, no repair).
- **B1 Retrieval+steering** — base + best-practice rubric via retrieval/steering, *no*
  verify loop (controls for "did the rules help, or the loop?").
- **B2 Self-consistency** — base, best-of-k sampling (controls for "is repair just more
  samples?").
- **Treatment T** — full judgment layer.

### 4.2 Benchmarks (chosen for a base-accuracy gradient → tests H3)
| Benchmark | Base one-shot | Role |
|---|---|---|
| HumanEval | ~97% | saturated; tests mechanism, near-zero headroom |
| MBPP | ~70-80% | mid headroom |
| **SWE-bench Verified** | ~30-50% | the headline; real repos, real `FAIL_TO_PASS` oracle |

Oracle = each task's **hidden** official test, never shown to the agent (prevents the
agent gaming the oracle; the agent only sees the task's *own* tests, as in real use).

### 4.3 Metrics
- **Primary:** VACR = % tasks passing hidden test AND with 0 human interventions.
- Secondary: false-done rate (H1), recovery rate (H2), escalation precision/recall (H4),
  per-class balanced agreement (H5), wasted tokens (tokens on tasks that still fail).
- **Reported with N and variance**; deltas not absolutes; never autonomy without
  correctness beside it.

### 4.4 Ablation (the attribution argument — the core of the paper)
Add one component at a time; isolate each component's marginal contribution to VACR:

| Arm | proceed | verify | self-repair | safety/escalate | personalization |
|---|:--:|:--:|:--:|:--:|:--:|
| A0 base | ✓ | | | | |
| A1 +verify | ✓ | ✓ | | | |
| A2 +repair | ✓ | ✓ | ✓ | | |
| A3 +safety | ✓ | ✓ | ✓ | ✓ | |
| A4 +personalize | ✓ | ✓ | ✓ | ✓ | ✓ |

If the VACR gain appears at **A2** and not before, repair is the cause (supports H2). If
A1 alone cuts false-done, verification is doing distinct work (H1). If A4 > A3 on
agreement, personalization is real (H5). This table is what lets us say *which part
works*, not just *that something works*.

---

## 5. Preliminary evidence (real, honest, insufficient alone)

HumanEval A/B, N=164, same base model:
- OFF 159/164 (97%) → ON 164/164 (100%); **false-done / human-fix events 5 → 0**;
  **6 first-shot failures recovered**, ON failed none.
- Interpretation: consistent with H1+H2 on a **saturated** benchmark (small Δ by design
  — there is almost no headroom at 97%). This is *evidence the mechanism fires*, **not**
  evidence of magnitude. Per H3, magnitude requires SWE-bench. We refuse to extrapolate.

---

## 6. Threats to validity (named, because reviewers will)

**Internal**
- *Tautological oracle:* a verify that checks the decision label, not its correctness,
  would inflate everything. Mitigation: discrimination test — each oracle must reject a
  known-bad trajectory (implemented; 5/5 discriminate so far).
- *Train/test leakage:* personalization data (overrides) feeding both training and the
  agreement eval. Mitigation: timestamped hard split.

**External**
- *Benchmark saturation:* HumanEval proves little. Mitigation: SWE-bench Verified is the
  headline; HumanEval is only a mechanism check.
- *Single-user personalization:* H5 evidence from one developer's 11 preference pairs is
  anecdotal. Mitigation: report as case study; do not generalize "learns anyone."

**Construct**
- *Metric gaming:* aggregate agreement is gamed by a constant predictor on a 96%-proceed
  distribution (a constant scores 0.96 aggregate / 0.25 balanced — measured). Mitigation:
  report **per-class balanced accuracy + confusion matrix**, never aggregate.
- *Goodhart on tests:* optimizing "pass the tests" can train test-gaming. Mitigation:
  hidden grading oracle + the human-preference channel as the alignment anchor.

**Cost**
- Token cost is not cleanly measurable via the CLI (~22k harness overhead/call swamps
  the signal). We report correctness + intervention deltas only; a clean cost study needs
  the raw API. We do **not** claim token savings.

---

## 7. Negative results we will publish (anti-hype commitment)

- The raw decision log is near-unlearnable: 89,529 episodes, **1 negative label**, 96%
  `proceed`, 11 human-preference pairs. We report this as a finding, not hide it — it is
  *why* synthetic data + a baseline rubric are necessary, and why we do not fine-tune now.
- If SWE-bench Δ VACR < +5 points, we will state the autonomous-completion thesis is
  unsupported and reposition the system as a safety/observability layer.

---

## 8. Contributions (what's novel if it holds)

1. A formalization of **VACR** (correctness ∧ zero-intervention) as the right success
   metric for autonomous coding agents, distinct from pass@k.
2. An **ablation methodology** that attributes autonomous-reliability gains to verify vs
   repair vs safety vs personalization — separating "the loop" from "the model".
3. A **data-first, baseline-then-personalize** design that gives day-0 value (cold-start
   solved) and a quality-gated synthetic pipeline that fixes class starvation.
4. Honest reporting: pre-registered refutation conditions, published negative results.

---

## 9. The one experiment that decides it

SWE-bench Verified, arms B0/B1/B2/T + ablation A0–A4, N≥50, hidden-test oracle, report
Δ VACR with variance. If T > all baselines and the gain localizes to A2 (repair) and
grows vs HumanEval/MBPP, the thesis holds. If not, it doesn't. Everything else is setup.
