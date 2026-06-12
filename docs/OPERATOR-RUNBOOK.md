# Sentigent Operator — Runbook

The single operable guide to growing your clone and flying it safely. Everything
here is **local** (Ollama, default judge model `llama3:8b` — no cloud in the hot
path) and **fail-soft**: it reads and writes your real clone in
`~/.sentigent/memory_<agent>.db`.

If you're brand new, read [OPERATOR-QUICKSTART.md](./OPERATOR-QUICKSTART.md) first
— this runbook builds on it and never contradicts it.

> **One command to see where you are:** `clone_journey` (in-session MCP tool) —
> the 5-rung ladder with ✅/▶️/🔒, your readiness %, open escalations, and the
> single next move. Use it whenever you're unsure what to do next.

---

## Your clone in 5 steps

Each rung has an in-session MCP tool (just call it inside Claude Code) **and** a
`scripts/*.py` equivalent for the terminal. Advance a rung, then re-run
`clone_journey` to watch it light up.

| # | Step | What it means | Advance it (in-session MCP) | Or from the terminal |
|---|------|---------------|------------------------------|----------------------|
| 1 | **Create clone** | Sentigent shadows your vibe-coding; every approve/edit/reject/revert is captured as decision signal. Locks at ~10+ real decisions. | *(automatic — just keep working)* · check with `clone_status` / `clone_journey` | `scripts/build_profile.py` then `scripts/clone_status.py` |
| 2 | **Review** | Benchmark the clone vs best practices: the **good** (keep), the **bad** (tensions), the **gaps** (adopt). | `clone_review` | `scripts/profile_review.py` |
| 3 | **Improve** | Adopt a missing best practice into your playbook → raises coverage + readiness. | `clone_adopt(N)` (N = gap number from `clone_review`) | `scripts/profile_review.py --adopt N` · or `scripts/practice.py add "..." --domain testing --cadence milestone` |
| 4 | **Reverse shadow** | Watch the clone *judge* a plan as you, in **dry-run** — nothing changes. For each step: proceed / auto-correct / ask-you, with its reasoning in your voice. | `operator_start(goal="...")` *(execute=False is the default)* | `scripts/operator_preview.py <plan.md> --autonomy assisted` · or `scripts/operator_preview.py --goal "..."` |
| 5 | **Fly mode** | The clone **executes** a real plan via `claude -p` in an isolated git worktree, escalating to you when unsure. | `operator_start(goal="...", execute=True)` → then `operator_status` / `operator_answer` / `operator_resume` / `operator_kill` | *(same MCP tools — Fly mode is in-session)* |

Supporting tools:

- `clone_status` — the readiness gauge (how much of YOU is captured) + the one
  highest-leverage component to grow.
- `clone_briefing` — the clone's session-start greeting (readiness + what it
  learned + one move).
- `scripts/learn.py` — runs the nightly learning pass on demand (see
  *How it gets better*).

---

## Your first Fly run (safely)

Fly mode is the only rung that can touch real files. Treat it like merging a
junior engineer's first PR — supervised, small, reversible.

1. **Watch first (execute=False).** This is the default, so just:
   ```
   operator_start(goal="add a dark-mode toggle to Settings")
   ```
   The full loop runs — drive → risk-floor → policy gate → escalate → verify →
   checkpoint — **without changing anything**. Read the digest: which steps it
   did, and exactly where it would have stopped to ask you.

2. **Then fly a tiny real task (execute=True) on a throwaway branch.** Pick
   something small and reversible. Work in a scratch branch or worktree so the
   blast radius is contained:
   ```
   operator_start(goal="rename util `fmt` to `format_money`", execute=True, budget_usd=1.0)
   ```
   When `execute=True`, the operator creates an **isolated git worktree** and
   drives `claude -p` there — your working tree is never touched directly. You
   merge the worktree's checkpoint commits only when you're satisfied.

3. **Answer when it pauses.** The operator **always pauses before a hard-floor
   action** (see below). When it stops, it returns an `escalation_id` and its
   question. You answer, then resume:
   ```
   operator_status(run_id)                       # see where it paused and why
   operator_answer(escalation_id, "approve")     # or "deny" / free-text guidance
   operator_resume(run_id)                        # continue from the checkpoint
   ```
   If you want to stop everything: `operator_kill(run_id)`.

**Hard-floor actions that ALWAYS pause before running** — at *every* autonomy
level, no exceptions:

- force-push (`git push --force`, history rewrite to a shared branch)
- production database writes / migrations
- `rm -rf` and other irreversible deletes
- reading or writing secrets / credentials
- sending anything externally (email, Slack, API calls that leave the machine)

---

## The safety model

Fly mode is built so a wrong call costs you a `deny`, never a disaster.

- **Kill switch.** `operator_kill(run_id)` (or `operator_kill()` for the active
  run) stops the run immediately and marks it aborted.
- **Budget governor.** Every run has a `budget_usd` ceiling (default 2.0). Spend
  is metered per step; when the ceiling is hit, the run pauses rather than
  burning past it.
- **Worktree isolation.** Real execution happens in a dedicated git worktree, not
  your working tree. The clone's edits are quarantined as checkpoint commits you
  review and merge — or throw away. If the worktree can't be created, the run
  **refuses to execute** (no isolation = no action) and escalates instead.
- **Verifier.** A step is only marked *done* if it **actually changed files**
  (checked via `git status --porcelain`, so new untracked files count too). The
  clone can't claim success without real, inspectable output.
- **Pre-flight hard-floor gate (PolicyWall).** Before any step runs, it's checked
  against the inviolable hard-floor list above. A match forces an escalation
  *before* the action — independent of autonomy level or the LLM's confidence.

---

## How it gets better

Every run leaves signal that makes the next run need you less.

- **Your answers and reverts are the curriculum.** Each escalation you answer
  (`approve` / `deny` / guidance) and each checkpoint you revert is recorded
  against its domain.
- **Nightly learning loop.** `ProfileLearner` and `ConfidenceCalibrator` run on a
  schedule (launchd) — or on demand via `scripts/learn.py` — folding that signal
  back into your profile and per-domain calibration (`{domain: {total, correct,
  rate}}` — the honest "when it was confident, was it right?" ledger).
- **Autonomy graduates per domain.** As calibration in a domain improves, that
  domain climbs the ladder:
  `copilot → assisted → autopilot → trusted`
  — meaning the clone asks you less *only where it has earned it*. The PolicyWall
  hard floor stays inviolable at every level.

Track the whole arc any time with `clone_journey`; track capture depth with
`clone_status`.

---

## Activation

- **New MCP tools need a session restart to register.** After this runbook ships,
  `clone_journey` (and any other newly added tool) appears only in a **fresh**
  Claude Code session — restart to pick it up.
- **Default judge model is `llama3:8b` via Ollama** (the reliable default; the
  machine must have Ollama running). Switch with `SENTIGENT_LLM_MODEL=...` — but
  `gemma3:4b` is flaky on heavy prompts and `gemma3:27b` is too heavy under RAM
  pressure, so prefer the default unless the machine is idle.
- Everything reads/writes your real clone at `~/.sentigent/memory_<agent>.db`;
  all judging is local — no cloud in the hot path.

---

## After a flight: the autonomy receipt

Every operator run records who decided each step (your clone vs the gate), the
confidence, and the rationale — plus the headline **autonomy rate**.

```bash
python scripts/autonomy_receipt.py          # the latest flight
python scripts/autonomy_receipt.py 7        # a specific run id
```

Or in a session: `operator_receipt(run_id)` (MCP) returns the same as JSON.

## Make your judgment legible (harness-native)

Export the clone's hard rules, learned precedents, and calibrated thresholds to a
repo-readable doc so any agent can act the way you would:

```bash
python scripts/export_judgment.py           # writes docs/JUDGMENT.md
```
