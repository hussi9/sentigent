# Design Research — what the agent-builders converged on, and where Sentigent sits

_Last updated: 2026-06-12. Living document. Append new research at the bottom; record the
resulting calls in `docs/DECISIONS.md`._

This is the research that feeds Sentigent's roadmap. It exists so any contributor — human or
agent — can see **why** the project is shaped the way it is, sourced to the primary writeups
from the teams building production coding agents. It is deliberately repo-legible (per the
"agent-first repository" practice below): read this, then `docs/DECISIONS.md`, and you have the
reasoning behind the code.

## The question

What have the teams shipping real agentic-coding systems (Anthropic / Claude Code, OpenAI /
Codex, Cognition / Devin, AWS+Kiro / "frontier teams") learned about the **harness** — the
scaffolding around the model — and what should Sentigent build vs. what does it already have?

## Sources

- Anthropic — [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- Anthropic — [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Anthropic — [Best practices for Claude Code](https://www.anthropic.com/engineering/claude-code-best-practices)
- OpenAI — [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- OpenAI — [Unlocking the Codex harness: how we built the App Server](https://openai.com/index/unlocking-the-codex-harness/)
- Cognition — [Don't build multi-agents](https://cognition.ai/blog/dont-build-multi-agents)
- AWS — [How frontier teams are reinventing AI-native development](https://aws.amazon.com/blogs/machine-learning/how-frontier-teams-are-reinventing-ai-native-development/)
- Kiro — [Frontier teams](https://kiro.dev/topics/frontier-teams/)

## Key findings, by source

### Anthropic — long-running harnesses
- An **initializer agent** sets up the run: writes `init.sh` (one command to restart the env),
  a **feature-list JSON** (granular end-to-end items, each with verification steps + a
  `passes: false` flag — agents may *only flip the flag*, never delete items), an initial git
  commit, and a human-readable `claude-progress.txt`.
- Every session **boots with a state-assessment sequence** before new work: confirm cwd → read
  git log + progress file → pick the highest-priority incomplete item → start the server → run a
  basic end-to-end verification test. This "protects against starting from a broken state."
- **Mandatory end-to-end verification before marking done** — code inspection is not enough;
  drive the feature like a user would (e.g. browser automation). Absent explicit prompting, the
  agent will change code and fail to notice the feature doesn't actually work.
- **Strictness against mutation**: JSON over Markdown for the checklist; "it is unacceptable to
  remove or edit tests." Commit + update the progress log at session close.
- **Compaction alone is insufficient** — durable external files (progress, feature list, git
  history) carry state that a summarized context window cannot guarantee.

### OpenAI — harness engineering
- **Humans steer, agents execute.** A 5-month experiment shipped a real product with zero
  hand-written code: 3 engineers, ~1,500 merged PRs, ~1M LoC, all written by Codex agents.
- **Rigid, mechanically-enforced architecture**: fixed layers with validated dependency
  direction (Types → Config → Repo → Service → Runtime → UI), enforced by generated linters,
  structural tests, and CI that blocks violating PRs.
- **Repository optimized for agent legibility** — the repo is the context; an agent should be
  able to reason about the whole domain from the repo itself. "The discipline shows up in the
  scaffolding, not the code."

### Cognition — don't build multi-agents
- A **single root agent that delegates isolated sub-tasks** beats free-form multi-agent. Multi-
  agent systems fail because decisions get dispersed and sub-agents act on conflicting
  assumptions; failure "boils down to missing context."
- **Share full traces, not just messages.** For long tasks, use a dedicated **compression model**
  that distills history into key events and decisions.
- Devin's team has publicly described a **"knowledge" memory that auto-generates memories from
  user corrections** (widely cited as ~95% auto-suggested rather than hand-written). _Note: this
  figure is from secondary summaries, not the linked post; treat as directional._

### AWS + Kiro — frontier teams
- **Steering files** (conventions, standards, testing patterns, codebase navigation) as
  persistent, multi-surface context — but teams hand-write them and they rot.
- **Multi-layer memory** = explicit steering rules + episodic session history + learned patterns
  that persist across contributors.
- **Spec-driven development**, **shift testing left** (agents run tests locally + self-correct),
  **parallel agents + async review**, and an **intentional 2-week "slowdown"** to encode expertise
  into reusable steering before going fast.

## The convergence

Across four independent teams, the same harness emerges:

1. **Single root agent**, not a swarm (Cognition).
2. **Durable external memory** beats context tricks (Anthropic, AWS).
3. **Learn from corrections** (Devin "knowledge"; AWS "learned patterns").
4. **Humans steer, agents execute** (OpenAI, AWS).
5. **Repo/context legible to the agent** (OpenAI, Kiro steering files).
6. **Verify end-to-end before "done"; self-correct** (Anthropic, AWS shift-left, OpenAI CI).

## Where Sentigent sits

| Convergent practice | Sentigent today | Status |
|---|---|---|
| Single root agent + delegated isolated work | operator loop + CloneResolver | ✅ have |
| Durable external memory > context tricks | SQLite brain (stronger than NOTES.md) | ✅ have |
| Learn from corrections | precedents from escalation answers (same mechanism as Devin "knowledge") | ✅ have |
| Humans steer, agents execute | autonomy ladder + escalation + hard-rule wall | ✅ have |
| Repo legible to agents | `AGENTS.md` learned-steering export (`scripts/export_steering.py`) | ✅ have (shipped 2026-06-12) |
| Multi-layer memory (explicit + episodic + learned) | profile/practices + episodes + precedents/calibration | ✅ have (Layer 1) |
| Per-session boot/state assessment + progress log | run_events + receipt; no explicit boot/progress file | 🟡 partial |
| Verify end-to-end before "done"; self-correct | verifier + self-repair exist; not gated on a real test run | 🟡 partial |
| Learned **team** patterns across contributors | `org_relationships` (stub) | 🔒 Layer 2 / roadmap |

**Read:** Sentigent independently matches the design four production teams converged on, and adds
the one layer none of them productized — **judgment, learned and local**. The gaps are narrow and
concrete, not architectural.

## Resulting build priorities (see `docs/DECISIONS.md` for the calls)

1. **Shift-left verification gate** — don't mark a step "done" until the project's own tests pass;
   self-correct on failure; never auto-clear the hard-rule wall. (Triple-endorsed: Anthropic's #1
   mechanism, OpenAI's CI enforcement, AWS shift-left.) → next.
2. **Frontier-formula receipt** — report the autonomy receipt as the three multiplicative factors
   (AI handles low-judgment work × uninterrupted high-judgment focus × instant expertise). → queued.
3. **Progress-log export (`PROGRESS.md`)** and a **"never delete tests/specs" hard rule** — cheap
   formalizations that map 1:1 to the Anthropic artifacts.
4. **Proactive memory suggestions** (spike) — after a correction, *offer* a precedent to confirm
   instead of only passively recording (the Devin "auto-suggested memory" pattern).

## Anti-patterns we explicitly avoid

- **Multi-agent swarms** (Cognition) — Sentigent stays single-root + resolver.
- **Invented metrics** — no modeled/illustrative numbers in public claims; only measured data
  from the brain (see `DECISIONS.md`, D-008).
- **Hand-written context that rots** — steering and judgment are *generated from behavior* and
  regenerated on demand.

---

## Verification (code review, 2026-06-12) — corrections to the "Where Sentigent sits" table

The table above was a feature-list claim. A line-by-line code review (and live execution) found
it was **too green** on the learning loop. Corrected statuses, with evidence:

| Claim | Reviewed status | Evidence |
|---|---|---|
| Operator loop: gate → resolver → escalation | ✅ **real** | `operate.py:252,465` (EscalationDecider), `:501` `clone.resolve(blocker)`, `:504` `should_apply` |
| Hard-rule wall is first branch, inviolable | ✅ **real** | `escalation.py:47` policy_wall is the first branch of `decide()` |
| Durable external memory (episodes) | ✅ **real** | 89,504 episode rows accrued on the live brain |
| Learn from corrections (precedents) | ⚠️ **coded-correct, but never fired live** | wiring exists (`mcp_server.py:3100`) but **the running MCP server is stale** — answering esc #7 wrote 0 precedents and returned the old `"recorded."` message. On-disk `learn_from_escalation_answer(7,'skip')` **does** work (precedents 0→1, id=1). Live brain: 0 precedents from 11 real answers. |
| Calibrated autonomy (thresholds from outcomes) | ⚠️ **running on static defaults** | `calibration_events = 0` → `thresholds_from_calibration` returns `{}` → resolver uses `DEFAULT_THRESHOLD`. The calibration math is correct but has no live data. |
| Verify end-to-end before "done"; self-correct | 🟡 **coded, no-op in dry-run, unproven in execute** | `operate.py:440` `verified = not execute` (dry-run skips verification); `:443` `Verifier(...).verify(...)` only runs in execute mode, which has never run live |

### The real finding
Sentigent's **judgment loop is genuinely wired**, but its **learning loops are effectively empty
in practice**: precedents never accrued (stale server) and calibration never accrued (no recorded
outcomes), so the resolver has been running ungrounded on defaults. The mechanisms are correct —
just proven by forcing a precedent to id=1 — but the *compounding* the project's pitch depends on
has not actually happened on this machine.

### Corrective actions (the real P0 — ahead of new features)
1. **Reload the running MCP server** so `operator_answer` actually calls the learn write-back.
   (On-disk code is correct; the deployed process is stale.)
2. **Backfill precedents from the 10 already-answered escalations** so the brain reflects real
   decisions (one created manually as id=1; the rest should be backfilled).
3. **Make outcomes flow into calibration** so thresholds stop being static defaults.
4. Only then do the new features (shift-left gate, etc.) sit on a loop that is actually learning.

_Lesson recorded in `DECISIONS.md` D-010: verify capability by executing it against the live
store, not by confirming the function exists._
