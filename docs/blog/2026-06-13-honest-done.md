---
title: "How Sentigent works — a judgment layer that makes a coding agent finish honestly"
date: 2026-06-13
author: Hussain Sehorewala
tags: [sentigent, ai-agents, architecture, evaluation, local-first]
summary: >
  A walkthrough of how Sentigent actually works — the decision pipeline every
  tool call passes through, the two separate loops (within-task repair vs
  cross-session learning), how it stays safe when running unattended, and the
  measured proof that it changes outcomes.
---

# How Sentigent works

Every AI coding agent has the same failure: it says **"Done!"** and it wasn't.
The model has no ground truth — "I finished" is a *claim*, and nothing forces it
to become a *fact*.

[Sentigent](https://github.com/hussi9/sentigent) is a small, MIT-licensed,
local-first layer that sits between a coding agent and its tools and makes "done"
earn its name. It doesn't make the model smarter — it adds **judgment** (should
this action happen?), **verification** (did it actually work?), and **autonomy**
(can it resolve its own blockers, and stop when it shouldn't?).

This post explains the machinery: the path a single tool call takes, the two
learning loops people constantly conflate, how it runs unattended without going
rogue, and what the numbers actually say. Everything maps to real modules in the
repo, and every claim is re-runnable.

---

## 1. The shape: a layer, not a model

Sentigent runs in two places, sharing one brain:

- **As hooks + MCP inside your agent** (e.g. Claude Code). A `PreToolUse` hook
  intercepts every Bash / Edit / Write / Agent call *before* it runs; a
  `PostToolUse` hook records what happened *after*. The agent can also call
  judgment tools directly (`sentigent_evaluate`, `sentigent_score`).
- **As an autonomous operator** (`sentigent/operator/`) — "fly mode" — that
  drives a headless worker through a plan on its own, stopping only when it
  genuinely needs you.

The brain is **local**: a SQLite file (`~/.sentigent/memory_<agent>.db`) plus
small local models via Ollama. No code, no decisions, no telemetry leave your
machine. That's a deliberate constraint, not a limitation — a judgment layer
sees everything you do, so it has to be yours.

---

## 2. What happens on one tool call (the decision pipeline)

Say the agent is about to run `rm -rf build/ && npm run deploy`. Before it
executes, the `PreToolUse` hook calls `Sentigent.evaluate()` (`core/engine.py`),
which runs a deterministic pipeline:

1. **Signals** — extract features of the action: is it destructive? does it touch
   prod / secrets / git history? how big is the diff? (`core/signals.py`)
2. **Baselines** — load what "normal" looks like for *you*, learned from your own
   history, falling back to profile defaults (`_get_baselines`). This is the
   "is this in-character for this operator?" layer.
3. **Precedent** — find similar past episodes by embedding similarity
   (`find_similar_episodes`). "Last time something like this came up, what did we
   decide, and how did it turn out?"
4. **Decision** — combine the above into one of four actions, with a calibrated
   `judgment_score`:
   - `proceed` — go ahead.
   - `enrich` — gather more context first (read more files, check docs).
   - `slow_down` — add validation, double-check.
   - `escalate` — **stop and ask the human.**

For `rm -rf … && deploy`, the signals trip a hard rule and it returns
`escalate` — the hook blocks the call and surfaces *why*. For a routine `npm test`
it returns `proceed` silently. After the tool runs, `PostToolUse` records the
real outcome (did the command fail? did the tests pass?) against that decision —
which is what makes the next decision better.

That's the loop you see in everyday use: **mostly invisible, speaks only when an
action deserves a second look.** On one real machine it has judged 89,523 actions
and intervened (non-`proceed`) on ~4% of them — a logger would show 0%.

---

## 3. Two loops people conflate — keep them separate

This is the crux, and where most "self-improving agent" claims fall apart.

### Loop A — within-task verify + self-repair (fixes *this* task)

In fly mode, when the operator finishes a step it does **not** trust the model's
"done." It runs the step's **Definition-of-Done** — the real test/build command,
a file-exists check, a grep, a non-empty-diff check (`operator/verifier.py`,
`operator/goal_dod.py`). If that fails, it feeds the failure back and retries,
bounded (`operator/operate.py`). 

The Verifier is **fail-closed** on purpose (decision D-018): an empty command or
empty file-list is a **FAIL, never a pass**. A missing oracle is danger, not
success — otherwise "no test" silently becomes "green," which is exactly the
hallucinated-done bug we're killing.

This loop makes the current task correct. It does **not** make the next task
better. That's Loop B.

### Loop B — cross-session learning (makes the *next* task better)

Every decision + outcome is an episode. Periodically the engine recomputes your
baselines from accumulated episodes (`update_baselines_from_episodes`), and when
you answer an escalation, that answer becomes a **precedent** the next similar
blocker resolves against automatically (`operator/backfill.py`,
`learn_from_escalation_answer`). Override rates feed a calibrator that nudges the
thresholds — if it escalated something you'd have waved through, it learns to
wave it through next time.

Calling Loop A "self-improvement" is the #1 piece of agent hype. We don't. Loop A
is repair; Loop B is learning. Sentigent runs both, and names them honestly.

---

## 4. Running unattended without going rogue

Autonomy is worthless if it's reckless, so fly mode is wrapped in a safety floor
(`operator/risk.py`, `operator/safety.py`):

- **PolicyWall** — deterministic hard rules that no amount of model confidence can
  override (touch prod creds, force-push, mass-delete → hard stop). It's "sticky"
  (D-020): if any matched rule fires the wall, the wall stays up even if a
  higher-scoring benign rule co-occurs.
- **CloneResolver** — a local model that answers routine blockers *as you* (from
  your learned profile) instead of halting the whole run for a trivial question.
- **EscalationDecider** — decides when a blocker is genuinely yours to make, and
  stops.
- **ChainGuard** (D-021) — watches for a *streak* of low-confidence
  auto-applied decisions and trips a circuit-breaker, so small drifts can't
  silently compound into a big wrong one. It also keeps a reviewable trail of
  every borderline call.
- **KillSwitch + BudgetGovernor** — a file you can touch to halt mid-run, and a
  token/step ceiling so an unattended loop can't run away.

The design rule: **autonomy is never reported without correctness beside it.**
A run that "finished 12 steps unattended" means nothing unless those steps passed
their own tests.

---

## 5. The proof (measured two ways, re-runnable)

### Receipt 1 — it judges, from a live brain

`sentigent_score()` / `sentigent_insights()` on one real machine:

| Metric | Value |
| --- | --- |
| Decisions judged (lifetime) | **89,523** |
| Non-trivial interventions | **3,495** — 3,176 enrich · 280 slow-down · 39 escalate |
| Per-tool correctness | Bash 1098/1098 · Edit 245/245 · Write 110/110 · Agent 26/26 |
| Calibration (Brier) | **0.039 → well-calibrated** |

### Receipt 2 — verify + self-repair vs one-shot (HumanEval A/B)

Same base model, same tasks. **OFF** = blank one-shot, graded on the official
hidden test. **ON** = generate → run the task's own tests → self-repair on
failure (≤3 attempts) → graded on the *same* hidden test the agent never sees. So
the delta is the verify+repair *mechanism*, not model quality.

```
HumanEval A/B — N=164, same base model both arms

  metric                          OFF (blank)   ON (Sentigent)
  verified pass@1                  159 (97%)      164 (100%)
  failures (= human-fix events)        5              0
  auto-self-repaired (no human)        —              6
```

Read it straight: the base model already passes **97%** one-shot, so the raw
delta is small — **+3 points**. The result that matters is the failure column,
**5 → 0**: every task the model got wrong on the first try, the verify→repair
loop recovered with **zero human help**, and ON failed nothing. That is the
honest size of the win — *it cleans up the model's misses unattended.* Big on the
slice that fails, modest in aggregate on a benchmark this saturated. On a harder,
realistic codebase (SWE-bench-style, lower base pass rate) the headroom — and so
the delta — should be larger; that study is future work, not claimed here.

**Honest cost caveat:** I can't give you a clean "X% fewer tokens" — the
`claude -p` CLI carries ~22k tokens of harness overhead per call, which swamps
the task tokens. So I report correctness and intervention deltas only, and will
do a real token study off the raw API rather than fake one here.

---

## 6. Re-run all of it

```bash
git clone https://github.com/hussi9/sentigent && cd sentigent
python eval/humaneval_ab.py --n 164 --max-attempts 3   # the A/B
sentigent_score()        # live-brain receipts
sentigent_insights()     # per-tool correctness + Brier
```

If a claim here can't be reproduced from that repo, it doesn't belong here.

---

## The one thing to remember

Sentigent doesn't make Claude smarter. It makes it **finishable without you
babysitting it**: judge the action, run the real test before claiming done, fix
its own failures, learn your corrections, and stop only when a human genuinely
has to decide. Two loops — repair and learning — kept honestly separate, wrapped
in a safety floor, all on your own machine.

— [github.com/hussi9/sentigent](https://github.com/hussi9/sentigent)
