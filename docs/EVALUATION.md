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
