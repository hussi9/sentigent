# Loop Engineering — the north star for Sentigent

> "My job is to write loops. The model is a subroutine; I'm the loop architect."
> — Boris Cherny (Anthropic), who reported 100% of his 259 PRs in 30 days were
> written by Claude Code loops, Dec 2025.

Loop engineering is the 2026 meta for AI coding: you stop *prompting* the agent and
start *designing the system that prompts it* — a loop that keeps pushing a plan to
completion, lap after lap, surviving the end of any single agent session. This doc
compiles the public state of the art and defines the **best version for Sentigent**.

## 0. THE OUTPUT METRIC — Faithful Autonomous Progress (FAP)

> The dark factory's one number: **given a VISION doc, how long and how faithfully can
> Sentigent push the plan before it needs a human?**

Everything below serves this metric. It is real, per-run, and impossible to fabricate —
it falls straight out of the loop's own state.

| Axis | Definition | Answers |
|---|---|---|
| **Distance** | plan steps completed ÷ total | *how long* it ran |
| **Fidelity** | steps that passed verification ÷ steps done | *how faithfully* (no drift/breakage) |
| **Autonomy** | blockers self-resolved ÷ blockers faced | did it need you? |
| **FAP** | **verified steps reached with zero human help ÷ total steps** | the headline (0–1) |
| **Faithful streak** | longest unbroken run of verified steps with no ask | longest hands-off span |

A run that drives 12/15 steps, all verified, paging you once = high distance, perfect
fidelity, one ask. A run that "finishes" but half the steps fail verification = high
distance, low fidelity = *not* faithful. **The product's job is to push FAP and the
faithful streak up over time** (as the learned push-vs-ask judgment improves). This
replaces every fabricated "judgment score" — the only number we report is the one the
loop actually produced.

## 1. What the field has converged on

**The Ralph loop (Geoffrey Huntley, 2025) — the seed.** `while :; do cat PROMPT.md | claude ; done`.
The insight that started it: **progress accumulates in files + git + tests, NOT in the
context window.** Each lap gets a *fresh context* over a re-derived plan. Failures pipe
back as a "contextual pressure cooker" that forces the model to fix its own mistakes.
Huntley built a whole programming language this way for ~$297.

**The loop contract (every production loop has 5 parts).**
| Part | Meaning |
|---|---|
| **TRIGGER** | timer (`every 15m`) or event (CI fail, PR comment) |
| **SCOPE** | which repos / files / PRs the loop may touch |
| **ACTION** | what the agent does each lap (ideally a named, tested skill) |
| **BUDGET** | max laps, token/$ cap, max sub-agents |
| **STOP** | done-criteria, iteration ceiling, spend limit, no-progress halt |

**Naive vs production loop (the hard part is *stopping*, not starting).**
- Open loop: agent writes until it says done → demo only.
- **Closed loop:** runs tests/lint/typecheck each lap, failures feed back → production-grade.
- Review loop: a background reviewer feeds findings back while context is fresh.
> "A loop with nothing to push back is the agent agreeing with itself on repeat."

**Durable state across sessions (Anthropic harness-design + harness-eng).**
Context windows are finite; every reset/compaction loses something, and agents that
sense low context do a "rushed finish." The fix: **state-persistence files** that let a
*new* session resume unambiguously —
- a **progress log** (what's done),
- **verification records** (what passed/failed),
- **next actions** (the stored next step).
Plus **anchor files** re-injected every lap: `VISION.md` (goal + success criteria),
`CLAUDE.md`/`AGENTS.md` (rules/guardrails), `PROMPT.md`/`loop.md` (the injected tick).
**Context reset + structured handoff beat compaction** for long runs (avoids "context anxiety").

**Three-agent shape (Anthropic).** Planner (spec) → Generator (implements in sprints) →
Evaluator (tests like a user via Playwright, grades on hard thresholds), communicating
**through files**. "Sprint contracts" = the generator proposes the work + its own success
criteria, evaluator approves, then it builds. Keep it as simple as the model allows.

**Cost is the new constraint.** Uber capped engineers at $1,500/mo after burning the
annual budget in 4 months. Controls that matter: hard max-iterations, **no-progress
detection** (halt if the same error repeats N×), and a pre-set $/token ceiling.

Sources: [Anthropic — Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) ·
[Loop Engineering 2026 guide (explainx)](https://explainx.ai/blog/loop-engineering-coding-agents-claude-code-guide-2026) ·
[Ralph Wiggum Loop (codecentric)](https://www.codecentric.de/en/knowledge-hub/blog/the-ralph-wiggum-loop-autonomous-code-generation-with-a-fresh-context) ·
[snarktank/ralph](https://github.com/snarktank/ralph) ·
[awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) ·
[Keeping context alive across sessions](https://walkinglabs.github.io/learn-harness-engineering/en/lectures/lecture-05-why-long-running-tasks-lose-continuity/) ·
[LangChain — Anatomy of an agent harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness)

## 2. The gap nobody has solved well — Sentigent's wedge

Everyone's loop **halts or runs off a cliff** at the two hard moments:
1. **A blocker** → naive loops stop and page a human (kills autonomy), or barrel ahead and
   do the wrong thing.
2. **No progress** → naive loops either spin forever (cost) or stop too early.

The decision *"push through this myself vs. stop and ask"* is exactly a **judgment** call —
and it's the one thing a generic loop can't do well. **Sentigent already has the parts to
make that decision *learned from your history*** — that is the differentiated loop:

- **Ralph gives autonomy but no judgment** (it just re-runs).
- **A bare harness gives structure but static rules.**
- **Sentigent = a durable loop harness whose push-vs-ask decision is learned + whose
  per-lap safety is org-enforced.** That's the version worth building.

## 3. The best version for Sentigent — architecture

```
        VISION.md (goal + Done-criteria)         org guardrail packs
                  │                                      │  (per-lap safety invariant)
                  ▼                                      ▼
   ┌────────────────────────── LOOP DRIVER (durable, cross-session) ──────────────────────────┐
   │  state file: progress log · verification records · NEXT STEP   (atomic, crash-safe)       │
   │                                                                                            │
   │  each lap:                                                                                 │
   │   1. read next step + anchor files (fresh context — Ralph discipline)                      │
   │   2. run a FRESH `claude -p` over just that step                                           │
   │   3. CLOSED-LOOP VERIFY (tests/typecheck/lint); failure pipes into next lap's prompt       │
   │   4. on blocker → CloneResolver decides push-or-ask using LEARNED thresholds               │
   │   5. STOP checks: DoD satisfied? · no-progress (same fail N×)? · max laps? · budget? · kill?│
   │   6. atomically persist → next step is durably queued before this session ends             │
   └────────────────────────────────────────────────────────────────────────────────────────┘
                  │ every lap logged → a real receipt (laps · verifies · resolves · asks · $)
                  ▼
        resume(loop_id) picks up at the stored next step after ANY session/crash
```

### What maps to existing code (we're ~60% there)
| Best-version part | Sentigent today | Status |
|---|---|---|
| Fresh-context laps (Ralph) | `operator/loop.py` `run_loop` (fresh runner/lap) | ✅ exists |
| Cross-session durable driver | `operator/loop_driver.py` (atomic state, `resume`) | ✅ built this session |
| Push-vs-ask on blockers | `operator/resolver.py` CloneResolver | ✅ exists |
| **Learned** push-vs-ask thresholds | `CloneResolver.thresholds_from_calibration` | ✅ exists — the wedge |
| Done-criteria STOP | `operator/goal_dod.py` GoalDoD | ✅ exists |
| Budget / kill STOP | BudgetGovernor / KillSwitch in `operate` | ✅ exists |
| Org guardrail packs (per-lap safety) | — | 🔨 to build (data-driven packs) |
| Closed-loop verify gate in the driver | partial (`verifier.py`) | 🔨 wire into loop_driver |
| No-progress detection (same fail N×) | — | 🔨 add to loop_driver |
| Anchor-file injection (VISION/CLAUDE) | — | 🔨 add to loop_driver |
| Receipt (laps/verifies/resolves/$) | `receipt.py` partial | 🔨 extend |

### Build plan (phased, each shippable) — ALL SHIPPED
- **P1 — durable loop core** ✅ `loop_driver.py` start/drive/resume, atomic state, cross-session resume (commit 00cc68e).
- **P2 — production discipline** ✅ anchor-file injection + closed-loop verify gate + retry pressure-cooker + no-progress halt + lap caps (in driver).
- **P3 — learned autonomy** ✅ CloneResolver wired into the blocker path; push-vs-ask uses learned per-category thresholds, in a killable child process under a hard budget; fail-soft to ask (commit c0e5d2d).
- **P4 — org guardrails** ✅ data-driven packs (`guardrails/*.yaml` + `operator/guardrails.py`) enforced as the per-lap safety invariant; opt-in (commit 3330cb5).
- **P5 — receipt + proof** ✅ `loop_driver.py receipt` aggregates FAP/distance/fidelity/autonomy across all runs — real numbers, no fabrication.

**Status: the loop harness is feature-complete (P1–P5). Next is real-world hardening —
run it with `--execute` on live visions to gather actual FAP, and wire the driver into
the MCP `operator_*` tools so the loop is callable from Claude Code directly.**

## 4. Positioning (honest) — compound learning is the moat

The industry has converged on a thesis (the Nadella / Microsoft framing, 2026): **the AI
era won't be won by whoever has the best model — intelligence is becoming a commodity. It's
won by whoever compounds human capital + token capital fastest, through the strongest
learning loop between humans and AI.** Ask the moat test: *"if we switched models tomorrow,
what would we lose?"* If the answer is "nothing," you have no moat.

Sentigent is that loop, as software you install — and it makes the answer
*"years of encoded workflows, judgment, guardrails, and faithful progress."* It maps 1:1:

| Industry concept | Sentigent component |
|---|---|
| **Token Capital** — intelligence encoded into systems (workflows, evals, playbooks, memory) | durable loop state + org guardrail packs + the local brain (every decision remembered) |
| **The Learning Loop** — seed → capture → apply at scale → learn from outcomes → compound | `loop_driver` fresh-context laps + closed-loop verify + CloneResolver learning push-vs-ask from your history; measured as FAP and **FAP-over-time** (§0) |
| **The moat test** | model-independent capital — switch models, keep your judgment, guardrails, and FAP |

So, concretely: Sentigent is **a loop harness with learned judgment**. It keeps pushing your
plan across session boundaries (Ralph's autonomy + durable resume), but it knows — from
*your* decision history — when to push through a blocker vs. stop and ask, and it enforces org
guardrails on every lap. Ralph is the engine; Sentigent is the engine that doesn't need
babysitting, won't drive off a cliff, and **compounds** — the one thing a rented model can't
give you. That compounding is the honest frontier: the FAP-over-time trend (§0) is how we
prove "the system gets smarter," not assert it.
