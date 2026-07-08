# Evaluation — does Sentigent measurably improve a coding agent?

The honest principle (see DECISIONS.md D-008): Sentigent does **not** make the base model smarter.
It adds *judgment, verification, and autonomy*. So we never claim "higher score because smarter." We
claim the measurable thing: **same base model, same tasks, Sentigent ON vs OFF → equal-or-better
correctness with less human intervention and less wasted spend.** Every number comes from a real A/B,
never a modeled counterfactual.

## North-star metric

**Verified autonomous completion rate** — % of tasks finished *with zero human intervention* AND
*passing the task's own tests*. The "AND" is the whole point: autonomy without correctness is worthless.

## KPI tree (most already instrumented in the brain / `RunResult`)

**1. Autonomy / toil reduction**
- Interventions per task (`RunResult.asks`) ↓
- Autonomy rate = blockers resolved-as-you ÷ all blockers (`RunResult.autonomy_rate`)
- Unattended run length (steps before a human is needed) ↑

**2. Quality / correctness** (the guardrail that makes Tier 1 credible)
- Verified-done rate — steps that actually passed `test_cmd` vs claimed done (Verifier)
- Override rate — how often the human corrects an auto-applied call (calibration; the "is the clone
  really me" metric)
- Defect / revert rate post-merge
- Borderline-chain interventions (D-021) — drift caught before it compounds

**3. Cost** — tokens / $ per *completed* task (`cost_events`), only from a real A/B.

## The protocol

**Benchmark fit.** Sentigent's value shows where an *autonomous loop with verification* matters — i.e.
tasks with a real test suite as the success oracle. Two tiers:

1. **HumanEval / MBPP (runs locally, no Docker, modest quota).** Function-level. The honest A/B here is
   **blank one-shot generation vs Sentigent's generate → run visible tests → self-repair loop**. The
   delta is attributable to the verify+repair *mechanism*, not model smartness.
2. **SWE-bench Verified (the headline study; needs Docker per repo).** Real GitHub issues whose success
   criterion (`FAIL_TO_PASS` / `PASS_TO_PASS`) is *exactly* what Sentigent's Verifier runs. Arms:
   Sentigent ON (resolver + verifier + chain-guard) vs blank agent. Report Δ verified-resolve rate,
   Δ interventions, Δ failed submissions, Δ tokens.

**Rules.** Same base model both arms · report deltas not absolutes · show N and variance · never report
autonomy without correctness beside it · the eval harness obeys "prove by execution" (real tests, real
subprocess — D-010).

## The Eval Card

Every eval run emits a standard report (a model-card analogue): base model, benchmark, N, and the ON-vs-OFF
deltas for the KPI tree above. Honest, reproducible, and the artifact a skeptic can re-run.

## Status

- Harness: `eval/` — A/B runner over a task set, emits the Eval Card. (Tier-1 first.)
- Headline SWE-bench Verified subset: planned; needs the Docker harness + a compute budget.

## Results — A0 vs A2 vs A3 ablation (2026-07-08)

Four arms exist over the verify→repair mechanism (`sentigent/eval/ablation/arms.py`):

- **A0** — one-shot, no repair.
- **A1** — verify-then-single-revise control (hard cap of one revision).
- **A2** — one-shot + a bounded repair retry on failure, unconditionally (repair
  always attempted on failure — the "generic retry loop").
- **A3** — same as A2, but each repair lap is **gated by the live Sentigent
  judge** (`sentigent.core.engine.Sentigent`, `profile="code_review"`): a
  repair lap is spent only when the judge returns a non-PROCEED verdict on
  the failing patch. This is the only arm that exercises the judgment engine
  itself, closing a gap flagged in a 2026-07-07 internal review: A0/A1/A2
  never call `Sentigent.evaluate()`, so their numbers show whether a generic
  retry-on-failure loop helps — not whether Sentigent's judgment adds
  anything on top of it.

### Table 1 — Real SWE-bench Verified instances (A0 vs A2), N=17

Reused verbatim from a prior real run (real repo clones, real Docker
containers, real `FAIL_TO_PASS` scoring, `claude -p` on the Claude
subscription — $0 metered) over the 17-task curated small-image subset
(`psf/requests`, `pallets/flask`, `pytest-dev/pytest`, `pylint-dev/pylint`,
`pydata/xarray`). A3 does not appear here — the real-instance runner
(`real_pilot.py`) only wires `a0`/`a1`/`a2`; it does not yet plumb the judge
into real-instance scoring, so no real-execution A3 number exists.

| Arm | Resolved | Rate | Repaired |
|---|---|---|---|
| A0 (one-shot) | 9/17 | **53%** | 0 |
| A2 (verify + bounded repair) | 13/17 | **76%** | 3 |
| **A2 − A0** | — | **+24 pts** | — |

N=17, no McNemar test — directional, not statistically significant. Source:
private dev-repo run log 2026-06-30 (`docs/WSB-REAL-FINDINGS.md`, "Pilot 2");
raw rows persisted in a local `AblationResultsDB` sqlite
(`task_id` = the SWE-bench instance id, `arm` ∈ {a0, a2}).

### Table 2 — Controlled toy harness (A0 vs A2 vs A3, live judge), N=50

Since no real-instance A3 wiring exists yet, A3 was run for the first time
ever in this session on a **controlled synthetic toy harness**
(`sentigent/eval/ablation/toy_batch.py`, ported from the private dev repo
alongside `arms.py`/`task.py`/`solver.py`/`results_db.py`). This is **not** a
re-run of real SWE-bench execution — the fixture is the toy `add()` bug used
throughout this harness's own tests. Each of 50 trials draws (once, seeded,
`seed=42`) whether a first patch is correct and whether a repair patch (given
failure feedback) would be correct, from Bernoulli rates calibrated to mirror
Table 1's empirical rates (first-pass 9/17≈53%→53% used; repair-success
4/8=50%). The **same** per-trial draw is reused across A0/A2/A3 so the three
arms differ only in *policy* (whether/when a repair lap is spent), not in
which task realization they see. A3 uses one **live**, freshly-initialized
`Sentigent(profile="code_review")` judge instance (isolated sqlite DB, not
`memory_hussain.db`, not the default `~/.sentigent/memory.db`) reused across
all 50 trials so it can genuinely accumulate state, exactly as it would in
production.

| Arm | Resolved | Rate | Avg attempts | Repaired |
|---|---|---|---|---|
| A0 (one-shot) | 23/50 | 46% | 1.00 | 0 |
| A2 (raw bounded repair, always attempted) | 34/50 | 68% | 1.54 | 11 |
| A3 (judge-gated repair) | 24/50 | 48% | 1.02 | 1 |
| **A3 − A2** | — | **−20 pts** | — | — |

N=50, seed=42, reproducible with the command below.

**Honest reading — whatever the number shows, it ships:**

- In this run, **A3 is not better than A2 — it is substantially worse.** Of
  the 27 trials where the first patch failed, the live `code_review`-profile
  judge returned a non-PROCEED verdict (and so authorized a repair lap) on
  only **1** of them; the other 26 were gated out with a PROCEED verdict,
  forfeiting repair opportunities A2 takes unconditionally.
- A one-off diagnostic call to the same judge on an identical context
  (fresh DB, first-ever call) returned `ENRICH` with reason *"Doubt signal
  active (0.60); Agent confidence low (0.50); Similar past episodes had mixed
  outcomes (0.50)"* and confidence 0.23 — i.e. weak, ambiguous signal. As the
  same judge instance accumulated more exposure to this identical low-signal
  context across the 50-trial run, its gate settled toward PROCEED (skip)
  rather than toward authorizing more repairs.
- **Caveat (stated plainly, not used to discount the number):** the
  `code_review` profile's signals/baselines are designed around risk
  decisions (destructive ops, change size, security, deployment safety), not
  around "is this failing patch worth another repair attempt." The context
  passed to `evaluate()` here (`tool_name`, `tool_input`, `attempts`,
  `hidden_test_failed`) is a thin, generic payload that doesn't feed the
  profile's designed signal set. This may be a profile/context mismatch
  rather than evidence that judgment universally hurts repair — but on the
  wiring that exists **today**, judge-gating this decision measurably
  *reduces* the resolved rate relative to unconditional repair. That is the
  number, and it ships.
- This is the first time A3 has been run at any scale (previously "defined
  and unit-tested, not yet run" per the private dev repo's 2026-07-07 review
  note). It directly answers the open question from that review: on the
  wiring built so far, **the judge's gating measurably subtracts value from
  a raw bounded-repair loop** rather than adding it. Whether that changes
  with a repair-specific signal set / profile is future work, not asserted
  here.

**Reproduction:**

```bash
cd sentigent-public
.venv/bin/python -m sentigent.eval.ablation.toy_batch --n 50 --seed 42
```

Full suite tail after adding the ported ablation harness + this run:
`904 passed, 15 skipped`.
