# Sentigent — the whole picture

> Visual version: **https://sentigent.xyz/diagrams** · Status legend: **live** = working
> today · **building** = on the roadmap.

Sentigent is a loop that carries your coding plan to "done" on its own, makes the
in-between calls from three layers of context, keeps a hard wall on dangerous actions,
learns from every blocker you answer, and reports one honest number.

```
                          THE SENTIGENT LOOP

 ── It improves itself ──────────────────────────────────────────  [live*]
   You ─▶ Loop runs ─▶ Result ─▶ Learnings ─┐
    ▲────────────────────────────────────────┘
   every blocker you answer becomes a precedent → it needs you less

 ── One run, step by step ─────────────────────────────────────────  [live]
   Plan ─▶ Act ─▶ Verify ─▶ Decide(go / ask) ─▶ Resume
   goal+    fresh   your        clone, as you      survives
   "done"   ctx     tests       hard rules→you     restarts

 ── Autonomy grows as it learns you ───────────────────────────────
   Watch ▸ Calibrate ▸ Trust ▸ Hands-off
   you-driven ───────────────────────────────▶ loop-driven
   (the loop acts · you stay the gate on force-push / prod / secrets)

 ── Foundations ───────────────────────────────────────────────────
   Profile[live] · Plan[live] · Policy[building] · LocalModel[live]
   · Memory[live] · FAP[live]
```

\* compounding loop: wiring is live and proven; thresholds visibly moving needs more
real answers per category to accumulate.

## The pieces

| Piece | Plain meaning | How it works | Status | Code |
|---|---|---|---|---|
| **Plan** | what to build + what "done" is | durable state on disk (`~/.sentigent/loops/`), survives sessions | live | `operator/loop_driver.py` |
| **Act** | does one step | fresh `claude -p` per lap | live | `loop_driver.py` |
| **Verify** | checks its own work | re-runs your done-criteria; fail → self-repair retry | live | `loop_driver.py` |
| **Decide** | go on or ask — as you | local clone answers push-vs-ask at a learned confidence | live | `operator/resolver.py` |
| **Resume** | survives crash/limit | reloads plan + position from disk | live | `loop_driver.py` |
| **Policy wall** | never-cross actions | force-push/prod-DB/secrets/rm/external always escalate | live | `core/policy_engine`, `operator/guardrails` |
| **Profile** | what you'd do | model-of-you; exports a steering file (AGENTS.md) | live | `resolver.py`, `scripts/export_steering.py` |
| **Memory** | what it remembers | local SQLite: episodes, rules, precedents, calibration | live | `memory/store.py` |
| **FAP** | one honest number | verified-with-no-help ÷ total, per run | live | `loop_driver.py receipt` |
| **Org Policy / registry** | org-wide rules + approved tools | unified control plane | **building** | roadmap R1–R6 |

## How it maps to the AWS "frontier team" lifecycle

| AWS AI-DLC | Sentigent |
|---|---|
| Self-improving compounding loop | the compounding loop (answer → precedent) |
| Inception → Construction → Operations → Evolution | Plan → Act → Verify → Decide → Resume |
| ProServe-Led → Customer-Owned | you-driven → loop-driven (autonomy transition) |
| "AI creates, humans verify" | loop acts · you gate the dangerous calls |
| Foundations (Operating Model · People · Platform · Governance · Security · Context) | Profile · Plan · Policy · Local model · Memory · FAP |

Two honest differences: **(1)** you're at the center, not a consulting team; **(2)** AWS
sells it top-down (paid consulting), Sentigent is bottom-up and open source — free for the
individual, paid only for the org control plane. See `docs/ROADMAP-STATEFUL-AGENT-OS.md`.
