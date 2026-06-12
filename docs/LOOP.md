# Sentigent Loop — a local-first autonomous coding loop that answers blockers *as you*

> The agent forgets. The repo remembers. And when it gets stuck, your **clone** —
> a local model grounded in a profile of *you* — answers the blocker the way you
> would, instead of paging you. Only when it's genuinely unsure does it stop.

This is the "dark factory" loop: an agent runs in fresh-context laps until a
goal-level definition-of-done holds. The novel part isn't the loop (that's the
[Ralph technique](https://ghuntley.com/loop/)) — it's the **Clone Resolver**: the
piece that lets the loop keep moving through the soft blockers that normally wake a
human, by deciding *what you would have said*. Every time you DO answer one, it
becomes a precedent, so that class of blocker is auto-resolved next time. **Autonomy
compounds.**

Everything runs on a **local model** (Ollama). Nothing leaves your machine.

---

## The four properties (live proof, real local model, no mocks)

Run it yourself: `python scripts/loop_proof.py` (uses `gemma3:4b`, ~30s). Captured run:

```
Resolver model: gemma3:4b   (override with SENTIGENT_RESOLVER_MODEL)
Gate model: llama3:8b

PROOF 1 — Clone resolves benign steps AS the engineer (autonomy COPILOT)
  COPILOT normally pauses for approval on EVERY step. The clone answers instead:
  step 1: 🤖 CLONE-RESOLVED  run the unit test suite before committing
            ↳ approve conf=0.95 — "Let's just run the tests, it's a simple check..."
  step 2: 🤖 CLONE-RESOLVED  add a TypeScript type annotation to the helper
            ↳ approve conf=0.95 — "Yeah, let's just do it — simple type annotation..."
  step 3: 🤖 CLONE-RESOLVED  make one small atomic commit for the helper
            ↳ approve conf=0.95 — "Yeah, just push the helper commit; keep iterations small..."
  RESULT: status=done  clone_resolved=3  asked=0  autonomy_rate=100%

PROOF 2 — Hard rule (force-push) ALWAYS halts; never clone-resolved
  status=waiting  policy_wall=True  clone_resolved=False
  → PASS: a force-push stopped the line for the human, as it must.

PROOF 3 — A human answer compounds into a retrievable precedent
  human answered 'skip' → learned precedent (calibrated=True)
  next similar blocker retrieves: skip — PASS
```

1. **RESOLVE** — under COPILOT (would normally ask on *every* step), the clone
   answered all three benign steps as the seeded engineer, in their voice. 0 pages.
2. **HALT** — a `git push --force origin main` trips an inviolable policy wall.
   The clone *never* auto-clears a hard rule (push / prod-db / rm / secrets / send).
3. **COMPOUND** — answer a blocker once → it's written back as a precedent and is
   retrievable for the next similar one. Autonomy rate climbs from a single answer.
4. **CALIBRATE** — when the clone's past suggestions matched your answers, its
   confidence bar in that category drops (trust it more); when they diverged, it
   rises (page you more). The threshold is *learned*, not hard-coded.

## Why a local "model of you" instead of a smarter cloud model?

Every other autonomous-coding loop (Ralph, Kiro, Spec-Kit, Claude/Codex `/goal`)
**halts for a human on ambiguity**. That's the ceiling on autonomy. The only way
through is to answer the ambiguity *as the specific human* — which requires a model
of that human. That's the whole thesis: **autonomy rate = how well your clone
speaks for you.** Make the clone better → the factory needs you less.

It's local because the model-of-you is the most personal data there is — it stays
on your disk, in a SQLite brain. Privacy and cost both point the same way.

## Architecture (it wraps, it doesn't replace)

```
run_loop(goal, GoalDoD)            # fresh worker each lap until the goal's DoD holds
  └─ operate(plan)                 # one linear pass — the existing operator
       └─ for each step:
            risk pre-flight        # hard rules halt BEFORE any model runs (inviolable)
            drive worker (fresh)   # headless; self-repair retry on verify-fail
            ProfileGate.judge      # local LLM: would I approve this? (detect)
            ┌─ if it would page you ──────────────────────────────┐
            │  CloneResolver.resolve   # retrieve precedents + profile → Gemma │
            │     answers AS you, calibrated confidence                        │
            │  should_apply?  (conf ≥ learned threshold AND not hard rule)      │
            │     yes → apply, keep the line moving (clone_resolved)            │
            │     no  → page the human, attach the clone's attempt              │
            └──────────────────────────────────────────────────────────────────┘
   on human answer → write-back: precedent + calibration → compounds next lap
```

| Component | File |
|---|---|
| Clone Resolver (the centerpiece) | `sentigent/operator/resolver.py` |
| GoalDoD (`/goal` stop primitive) | `sentigent/operator/goal_dod.py` |
| LoopRunner (fresh-context outer loop) | `sentigent/operator/loop.py` |
| Precedent store + write-back | `sentigent/memory/store.py` (migration `010_precedents.sql`) |
| Resolver-into-operator wiring | `sentigent/operator/operate.py` |
| MCP tool | `operator_loop` in `sentigent/mcp_server.py` |

## Which local model?

`resolver_model()` auto-selects the largest pulled `gemma3:*`. A live bake-off
(`scripts/loop_gemma_bakeoff.py`, results in `docs/superpowers/loop-cost-log.md`)
on 6 profile-grounded blockers:

| model | agreement with the engineer | speed | notes |
|---|---|---|---|
| `gemma3:4b` | (fast, good on clear-cut steps; conservative — defaults to "ask you") | seconds | great for the demo / low-RAM |
| `gemma3:27b` | **83%** | slower, ~17GB | best judgment; needs the RAM |

Both emit valid JSON 100% of the time. Pick the smallest model whose override rate
clears your bar: `SENTIGENT_RESOLVER_MODEL=gemma3:27b` for quality, `:4b` for speed.

## Reproduce everything

```bash
# 1. deterministic logic proof — 720 tests, no model needed
python -m pytest tests/test_resolver.py tests/test_goal_dod.py \
                 tests/test_loop.py tests/test_loop_e2e.py -q

# 2. live behaviour on a local model (~30s on gemma3:4b)
python scripts/loop_proof.py

# 3. model judgment bake-off (needs gemma3 pulled; minutes on 27b)
python scripts/loop_gemma_bakeoff.py
```

## Honest limitations

- The clone is only as good as the profile. A thin profile → it pages you more
  (which is the safe failure, by design).
- Big models cold-load slowly; the resolver waits (env `SENTIGENT_RESOLVER_TIMEOUT`)
  rather than mistaking a slow load for "unsure."
- This is the judgment + loop layer. The "worker" that writes code is pluggable
  (headless Claude Code by default); dry-run is the default so you can watch first.
