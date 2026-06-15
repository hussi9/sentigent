# Sentigent — Prove-or-Kill Roadmap

> The discipline: **one metric, gated phases, a pre-committed kill switch at each
> gate.** We decide the GO/KILL number *before* running the phase, so we can't
> rationalize a bad result into "promising." If a gate fails, we stop or pivot —
> no sunk-cost momentum.

Date: 2026-06-13. Status of evidence today: HumanEval A/B done (N=164,
OFF 159→ON 164, 5→0 human-fix events). That proves the mechanism on *easy* tasks.
It does **not** prove usefulness on real work. This roadmap exists to settle that.

---

## The one metric (everything gates on this)

**VACR — Verified Autonomous Completion Rate** = % of tasks that finish
**(a) passing the task's own hidden tests AND (b) with zero human intervention.**

We always report **Δ VACR = ON − OFF**, same base model both arms. We pair it with
**interventions-per-completed-task** (the autonomy cost) — a win is *more correct,
fewer touches*.

---

## Phase 1 — Reality check on hard tasks  ⏱ ~3–5 days · 💰 capped

The make-or-break. HumanEval is saturated (97% base) → no headroom. Real work fails
often, which is where verify+repair *should* pay.

- Build a **SWE-bench Verified** harness (Docker per repo; `FAIL_TO_PASS` /
  `PASS_TO_PASS` is exactly Sentigent's Verifier oracle).
- Run **N = 25** instances, ON vs OFF, same base model.

### 🔴 KILL GATE 1 (pre-committed)
| Result | Decision |
| --- | --- |
| **Δ VACR ≥ +10 pts** | GO → Phase 2 |
| +5 to +10 pts | GO, but narrow scope to "assisted repair," not "autonomous" |
| **< +5 pts** | **KILL the autonomous-coding thesis.** Reposition Sentigent as a *safety + honest-done observability* layer only. Stop here. |

Budget ceiling: if the run blows its token/$ cap before finishing N=25 → auto-pause,
treat as a fail signal, re-scope.

---

## Phase 2 — Scale + tune (only if Gate 1 = GO)  ⏱ ~1–2 wks

- Scale to **N ≥ 100**. Improve the weakest links: Definition-of-Done inference,
  repair-prompt quality, the chain-guard threshold.
- Re-measure Δ VACR and wasted-tokens.

### 🔴 KILL GATE 2
- Δ VACR **holds at scale** (within noise of Phase 1) **and** wasted tokens not
  worse → GO → Phase 3.
- Δ VACR collapses at scale → **stop tuning, ship the proven slice**, skip Phase 3.

---

## Phase 3 — Prove the *learning* loop (the unproven half)  ⏱ ~1 wk

This is the part most at risk of being nonsense. Test it directly.

- Run a stream of *related* tasks twice: once **brain ON** (precedents/calibration),
  once **brain reset** each task. Measure **interventions-per-task over time**.

### 🔴 KILL GATE 3
| Result | Decision |
| --- | --- |
| Interventions/task **declines** with brain ON vs reset | GO — the clone/learning story is real, keep + market it |
| **Flat / no difference** | **KILL the "self-learning clone" story.** Cut it from product + all marketing. Keep verify/repair/safety. |

---

## Phase 4 — Make it usable (only after the metric is proven)  ⏱ ~1 wk

Do **not** polish before the metric passes. If Phases 1–3 pass:
- One-command install, the always-on engagement banner (shipped), clear docs,
  a real "what did Sentigent do for me" report.

---

## THE KILL SWITCH PLAN (the meta-rule that governs all of it)

1. **Pre-commit the number.** Each gate's GO/KILL threshold is written here *before*
   the phase runs. No moving the goalposts after seeing results.
2. **Budget ceiling per phase.** A hard token/$ cap. Blowing the cap without hitting
   the gate = automatic KILL signal, not "just a bit more."
3. **Two-strike rule.** Two consecutive gates missed → **abandon the
   "autonomous coding product" thesis entirely** and fall back to the narrow,
   proven tool (honest-done verify + safety floor). No third chance.
4. **Honest log.** Every gate's real numbers (pass or fail) get committed to
   `eval/results/` and `docs/PROOF.md`. Failures are published too.
5. **Default = KILL.** If a gate is ambiguous or unrun by its deadline, the default
   decision is KILL/pause, not "keep going on faith."

---

## What this protects against

This whole conversation kept circling "is it worth it / is it nonsense." This plan
makes that a *measured decision* instead of a feeling: either the numbers clear the
gates (real tool — invest), or they don't (kill the overclaim, keep the honest
narrow core). Either outcome is a win, because either way we stop guessing.

> **Immediate next action:** build the Phase-1 SWE-bench harness and run N=25.
> That single number decides whether Sentigent is a product or a feature.
