# Sentigent

**A local-first judgment layer + autonomous loop for AI coding agents.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Most "autonomous" coding agents are autonomous right up until the first ambiguity — then they stop and ask you. Sentigent closes that gap. It gives an agent two things it can't get from a bigger model or a better prompt:

1. **Judgment** — before a risky action (deploy, `rm -rf`, prod DB, secrets, force-push) it decides *proceed / slow down / escalate*, from what it has learned about your past decisions — not hand-written rules.
2. **A loop that keeps running** — when the agent hits a blocker, a **local model of *you*** answers it the way you would, instead of paging you. It only stops when it's genuinely unsure or hits a hard rule.

Everything runs **on your machine** — a SQLite brain on disk + a local Gemma model via [Ollama](https://ollama.com). A model of how you make decisions is the most personal data there is; none of it leaves the box.

---

## See it work in 30 seconds

Requires Ollama with a Gemma model pulled (`ollama pull gemma3:4b`).

```bash
git clone https://github.com/hussi9/sentigent && cd sentigent
pip install -e .
SENTIGENT_RESOLVER_MODEL=gemma3:4b python scripts/loop_proof.py
```

You'll watch a real local model:
- resolve benign blockers **as the seeded engineer** (no human paged),
- **halt** on a `git push --force` — a hard rule the clone can never auto-clear,
- turn a human's answer into a **precedent** it reuses next time.

The logic is covered by deterministic tests (no model needed): `python -m pytest -q`.

---

## How it works

```
A blocker appears
      │
      ▼
┌────────────────┐  confident & not a hard rule   ┌───────────────┐
│ Clone Resolver │ ──────────────────────────────▶│ answer as you  │ → loop keeps moving
│ local Gemma +  │                                 └───────────────┘
│ your profile + │   unsure ── or ── hard rule
│ past decisions │ ────────────────────────────────▶  page the human
└────────────────┘                                       │
                                                          ▼
                                       you answer once → it becomes a precedent
                                       → next time the clone handles it itself
```

The more blockers you answer, the fewer it needs you for. That compounding autonomy is the whole point. → **[docs/LOOP.md](./docs/LOOP.md)** explains the loop and the Clone Resolver in full.

**Two layers:**
- **Layer 1 — local SQLite brain.** Judgment, the loop, the clone, precedents, calibration. Fully working, zero network. This is what you use.
- **Layer 2 — optional team sync (Supabase).** Share patterns across agents/machines. Off by default; not needed to fly solo.

---

## How to operate it ("flying")

Sentigent installs into Claude Code as an MCP server + hooks, then you drive it in plain language and clear blockers with one line.

**1. Install** → **[docs/OPERATOR-QUICKSTART.md](./docs/OPERATOR-QUICKSTART.md)**

**2. Check it's alive** (in a Claude Code session):
```
Run clone_status and sentigent_score.
```

**3. Fly a goal:**
```
Plan this, then operate it to done with the Sentigent loop: <your goal>.
Autonomy = assisted.   Stop only for hard rules or when the clone is unsure.
```
Dial autonomy up as you trust it: `copilot → assisted → trusted → autopilot`.

**4. When it pauses and asks you** (the loop working):
```
operator_answer(7, "approve")     # or "skip" / "takeover"
```
That answer trains the clone, so it stops asking next time.

**5. Steer / stop:**
```
operator_status(<run_id>)    # where it is, what's pending
operator_kill                # halt now — the hard-rule wall is always on
```

Day-to-day operating guide → **[docs/OPERATOR-RUNBOOK.md](./docs/OPERATOR-RUNBOOK.md)**.

---

## Docs

The three docs that matter — written to understand and run the project:

| Doc | What it's for |
|---|---|
| [docs/LOOP.md](./docs/LOOP.md) | Understand the loop + Clone Resolver |
| [docs/OPERATOR-QUICKSTART.md](./docs/OPERATOR-QUICKSTART.md) | Install + your first flight |
| [docs/OPERATOR-RUNBOOK.md](./docs/OPERATOR-RUNBOOK.md) | Operate day-to-day: autonomy, escalations, kill switch |

---

## Honest status

- **Layer 1 (local judgment + loop): real and tested** — what you use every day.
- **Layer 2 (Supabase team-sync): built but optional/dormant** — only for multi-agent / multi-machine sharing.
- Research-grade open source, not a turnkey product. Teardowns and issues welcome.

## License

MIT
