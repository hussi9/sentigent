# Sentigent Signals — Learning → Thinking → Acting

The reward is **Acting** (did it complete the task, untouched, correct). But that's
a **lagging** signal — by the time it drops, the failure already happened upstream.
So each layer below the reward has its own **leading** signals that warn us *before*
the next layer fails.

```
LEARNING  ──leads──▶  THINKING  ──leads──▶  ACTING (reward)
(is the brain         (is the judgment       (did the work land:
 actually absorbing    sound before the        correct + zero-touch)
 me?)                  action?)
```

Failure propagates downward. So we watch the **top** to predict the **bottom**:
*learning stalls → thinking degrades → acting fails.* Catch it at learning.

---

## LAYER 3 — ACTING  (the reward · LAGGING)

What the user feels. The thing we ultimately sell.

| Signal | 🟢 Good | 🔴 Failing | Status |
| --- | --- | --- | --- |
| **Δ VACR** (correct AND zero-touch, ON−OFF) | ≥ +10 pts on hard tasks | < +5 pts | harness exists (HumanEval); SWE-bench = Phase 1 |
| **Human-fix events** per N tasks | trending ↓ | flat/↑ | measured (5→0 on HumanEval) |
| **Defect / revert rate** post-merge | low, ↓ | ↑ | to build (needs git follow-up) |

> Acting is the scoreboard, not the early warning. Never tune on this alone.

---

## LAYER 2 — THINKING  (LEADING indicator of Acting)

Decision quality *before* the action lands. If thinking rots, acting fails next.

| Signal | What it catches | 🟢 Good | 🔴 Failing | Status |
| --- | --- | --- | --- | --- |
| **Calibration / Brier score** | confidence not matching reality | ≤ 0.10 | rising toward 0.25 | **measured: 0.039** (`sentigent_insights`) |
| **Override rate** — % of auto-applied calls the human reverses | the clone misjudging *as you* | ≤ ~10%, ↓ | ↑ | partial — needs the borderline-trail wired to outcomes |
| **Escalation precision** — when it stopped to ask, was it right? | crying wolf (wastes you) | high | many needless stops | partial (chain-guard trail) |
| **Escalation recall** — did it ask when it *should* have? | the dangerous one: acting on what it should've escalated | ~100% | any miss | **build** — the false-negative is the real risk |
| **Verifier catch-rate** — % of false "done" it caught | hallucinated completion slipping through | high | vacuous passes | measured indirectly (fail-closed verifier) |

> The asymmetry that matters: a **false-positive escalation** costs you a minute.
> A **false-negative** (it didn't stop when it should have) is how an autonomous run
> does damage. Weight recall over precision here.

---

## LAYER 1 — LEARNING  (LEADING indicator of Thinking)

Is the brain actually absorbing *you*? If this stalls, thinking can't improve, so
acting can't improve. This is the earliest warning — and the part most at risk of
being theater.

| Signal | What it catches | 🟢 Good | 🔴 Failing | Status |
| --- | --- | --- | --- | --- |
| **Precedent capture rate** — answered escalations that become reusable precedents | answers going into a void | ~100% of answers → precedent | answers not stored | **was broken (11 answered, 0 precedents) → fixed via backfill.** Now watch it stays green |
| **Precedent reuse rate** — % of new blockers resolved by an existing precedent vs re-escalated | learning not compounding | ↑ over time | flat near 0 | **build** — this is the proof learning works |
| **Override-rate decline on familiar work** | the clone not converging to you | ↓ over repeated similar tasks | flat | **build** (this is roadmap KILL GATE 3) |
| **Coverage** — % of your recurring decision-types with a learned baseline | blind spots | rising | stuck | partial (`learned_baselines` in `sentigent_score`) |

> The single make-or-break learning signal: **precedent reuse rising + override
> declining on familiar work.** If both are flat, the "self-learning clone" is dead
> weight — cut it, keep verify/repair. (That's the Phase-3 kill gate.)

---

## How they chain (the early-warning logic)

| If this LEADING signal slips… | …you'll see this LAGGING failure next |
| --- | --- |
| Precedent reuse flat (Learning) | Override rate rises (Thinking) |
| Override rate rises (Thinking) | Brier worsens (Thinking) |
| Brier worsens (Thinking) | VACR drops, human-fixes rise (Acting) |

So the dashboard reads **top-down**: a red at Learning today predicts a red at
Acting in a week. Fix upstream.

---

## The minimum dashboard (4 numbers to watch weekly)

1. **Δ VACR** (Acting reward) — the scoreboard.
2. **Brier score** (Thinking) — is judgment calibrated? *(0.039 now)*
3. **Override rate trend** (Thinking↔Learning bridge) — is the clone right, and getting righter?
4. **Precedent reuse rate** (Learning) — is it actually learning, or just logging?

If #2/#3/#4 are green, #1 is *predicted* green before you run the expensive eval.
That's the whole point of leading metrics: stop paying for the lagging surprise.

---

### What's real today vs to-build
- **Real now:** Brier (0.039), per-tool correctness, learned baselines, precedent
  capture (post-fix), the borderline/chain trail.
- **Build next (in priority order):** precedent-reuse rate, override-rate-over-time,
  escalation recall test, VACR on SWE-bench. The first three are cheap (read the
  brain); the fourth is the Phase-1 gate.
