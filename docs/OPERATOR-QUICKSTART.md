# Sentigent Operator — Quick Start (the part you can use today)

All local (Ollama, no cloud). All read/write your real clone in
`~/.sentigent/memory_<agent>.db`.

## The clone lifecycle (where each step lives)

| Step | What it is | Command / status |
|---|---|---|
| 1. **Create clone** (shadow) | sentigent watches your vibe coding → a profile of you | `build_profile.py` + the live capture hook |
| 2. **Review** the clone | the good, the bad, the missing gaps, suggestions | `profile_review.py` ✅ |
| 3. **Improve** the clone | adopt best-practice suggestions (universal/org) | `profile_review.py --adopt N` ✅ |
| 4. **Reverse shadow** | the clone works, you watch it judge as you | `operator_preview.py` (dry-run) ✅ |
| 5. **Fly mode** | the clone executes a goal+plan for you | next (real `claude -p` drive) |

Track progress toward "clone ready" any time with `clone_status.py`.

## 1. Build / refresh your clone

Models your CLAUDE.md + captured decision signal into a structured "model of you".

```bash
cd ~/devpro/sentigent
.venv/bin/python scripts/build_profile.py            # uses llama3:8b (reliable default)
.venv/bin/python scripts/build_profile.py --show     # print the latest stored profile
# switch model anytime (both pulled): SENTIGENT_LLM_MODEL=gemma3:27b ... (machine must be idle)
```

## 2. Watch the Clone Readiness gauge

How much of YOU is captured, as a live %, with the one next move that raises it.

```bash
.venv/bin/python scripts/clone_status.py
```

It climbs as you: build the profile, declare practices, and just keep working
(your approvals / edits / reverts are captured automatically by the Phase-0 hook).

## 3. Declare your build practices (the "how I build" playbook)

```bash
.venv/bin/python scripts/practice.py add "Run the full test suite before a milestone commit" --domain testing --cadence milestone
.venv/bin/python scripts/practice.py add "Self-review the full diff before opening a PR" --domain review --cadence pr
.venv/bin/python scripts/practice.py list
```

Each practice (1) raises clone readiness, (2) the Operator judges your work
against, and (3) gets adherence-tracked from your real signal.

## 3b. Review your clone against best practices (the good / bad / gaps)

```bash
.venv/bin/python scripts/profile_review.py            # full review + suggestions
.venv/bin/python scripts/profile_review.py --adopt 1  # adopt suggestion #1 into your playbook
```

Benchmarks your profile + practices against universal best practices (and any in
`~/.sentigent/org_best_practices.json`). Shows **the good** (keep), **the bad**
(tensions to watch — e.g. "never pause" vs "confirm before destructive"), and
**missing gaps** you can adopt one at a time to raise your best-practice coverage.

## 4. Watch the Operator judge a plan AS you (dry-run — nothing executes)

```bash
.venv/bin/python scripts/operator_preview.py examples/sample-plan.md --autonomy autopilot
.venv/bin/python scripts/operator_preview.py myplan.md --autonomy assisted
.venv/bin/python scripts/operator_preview.py --goal "ship the dark-mode toggle"
```

For each step it shows **proceed / auto-correct / ask-you**, the risk floor, and
its reasoning in your voice. PolicyWall hard rules (force-push to main, prod DB,
external email, rm -rf) ALWAYS ask, at every autonomy level. The headline metric
is the longest unattended run — how far it gets between the steps where it'd stop
to ask you. As your clone grows, that number climbs.

### Autonomy levels
- `copilot` — approve every step (harvests signal fastest)
- `assisted` — auto low-risk; asks on risky/novel (good default)
- `autopilot` — unattended; asks only on real triggers
- `trusted` — asks rarely; PolicyWall still inviolable

## What's real vs. what's next

**Real today:** profile synthesis, clone-readiness gauge, practices playbook +
adherence, the full judgment loop (risk floor → would-you-approve verdict →
escalation decision), all dry-run and visible.

**Next (Phase 1+):** the Operator actually *drives* `claude -p` step-by-step with
your one-tap approval over Telegram, in a git worktree, with checkpoint commits —
then learns from your approvals/reverts so each run needs you less.
