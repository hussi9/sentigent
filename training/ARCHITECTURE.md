# Sentigent Learning System — Design Architecture & Implementation Plan

> Status: DESIGN (spec-driven). This is the single source of truth. The scattered
> artifacts already built (`principles.yaml`, `lifecycle.yaml`, `packs/`,
> `compose.py`, `build_dataset.py`, `DATA.md`) are components OF this design — this
> doc is what they should have derived from. Written to dogfood our own rubric:
> spec-first, plan-with-DoD, kill-gated.

---

## 1. Vision (one sentence)

A **data-first** system that makes any coding agent behave like a senior developer
on day 0 (baseline best practices) and like *you* over time (personalization),
where the durable asset is the **dataset**, not the model.

## 2. The problem this solves (proven, not assumed)

- "Learn from me" is unviable from raw logs: 89,529 episodes but **1 negative,
  96% `proceed`, 6 `escalate`, 11 HITL pairs.** Unlearnable as-is. (Measured.)
- Cold-start: a clone with zero data is useless on day 0.
- Portability: a Claude-Code-only ruleset dies when the agent/model changes.

## 3. Architecture (the layers, and why each exists)

| Layer | Artifact | Purpose | Durable? |
|---|---|---|---|
| **L1 Principles** | `principles.yaml` | first-principles SWE rules, agent-agnostic, full SDLC | ✅ the IP |
| **L1.5 Lifecycle** | `lifecycle.yaml` | macro agentic SDLC: phases + exit-gates + agent invariants | ✅ the IP |
| **Packs** | `packs/*.yaml` | composable dev-practice sets (TDD, spec-driven, security-first) that adjust+expand baseline | ✅ the IP |
| **Composer** | `compose.py` | baseline + opt-in packs → effective ruleset (safety floor locked) | tooling |
| **L2 Adapters** | `adapters/<agent>.yaml` | bind abstract principles → a specific agent's primitives (claude_code, codex) | swappable |
| **L3 Personalization** | brain + `build_dataset.py` | your overrides/answers bend only `personalizable: true` rules | ✅ your moat |
| **Data pipeline** | `gen_synthetic.py`, `build_dataset.py` | rules → quality-gated training data (D2) + HITL (D3) | engine |
| **Model** | LoRA/DPO on local resolver | consumes the data; LAST + swappable step | commodity |

**Composition order at runtime:** `baseline ⊕ packs → effective ruleset → bound through agent adapter → personalization bends soft rules`.

## 4. Data model (the product) — see DATA.md

- **D1 Rubric** = L1 + lifecycle + packs (curated, versioned, verifiable).
- **D2 Synthetic corpus** = D1 → teacher → trajectories → **quality-gated** → SFT fuel. Fixes class starvation.
- **D3 Preference stream** = your live overrides/answers → DPO/RLHF fuel.
- Every record carries provenance `{label_source, rule_id, dataset_version}`.

## 5. Training pipeline (offline → live)

```
D1 rubric ──teacher (claude -p)──▶ candidate trajectories
                                        │ QUALITY GATE (verify per rule)  ← non-negotiable
                                        ▼
                D2 SFT corpus (balanced) ──┐
                D3 preference pairs ────────┤
                                           ▼
              SFT (LoRA on local resolver) → DPO (on D3) → LIVE RLHF loop
                                           ▲                     │
                                           └──── overrides ──────┘  (flywheel)
```

## 6. Acceptance criteria (how we know the design is realized)

- [ ] `compose.py` emits an effective ruleset from baseline + N packs, safety floor un-weakenable. ✅ (36 rules)
- [ ] `build_dataset.py` extracts D2/D3 from the brain with provenance. ✅ (3,441 / 11)
- [ ] `gen_synthetic.py` generates ≥200 *verified* examples per rare class (escalate/slow_down). ⛔ TODO
- [ ] An L2 adapter exists for ≥2 agents (claude_code, codex). ⛔ partial
- [ ] Held-out **agreement-rate** eval exists (the "like-me" metric). ⛔ TODO
- [ ] One source of truth for L1 (dedupe `best_practices.yaml` ↔ `principles.yaml`). ⛔ TODO

## 7. Implementation plan (phased, DoD + kill gate per phase)

**Phase 0 — Consolidate (½ day)**
- DoD: `best_practices.yaml` retired → its Claude content becomes `adapters/claude_code.yaml`; `principles.yaml` is sole L1; `compose.py` green; this doc committed.
- Kill gate: none (cleanup).

**Phase 1 — Synthetic generator + quality gate (2–3 days)**
- DoD: `gen_synthetic.py` runs compose → teacher → verify-gate → writes D2; drop-rate logged; ≥200 verified examples for each of escalate/slow_down.
- 🔴 Kill gate: if quality-gate drop-rate >70% (teacher can't produce verifiable trajectories), the rubric `verify` specs are wrong → fix rubric before scaling.

**Phase 2 — Adapters (1 day)**
- DoD: `adapters/claude_code.yaml` + `adapters/codex.yaml` bind every principle id; generator renders agent-specific data from each.
- Kill gate: none.

**Phase 3 — "Like-me" eval (1 day)**
- DoD: held-out set of your real decisions; report clone↔you **agreement rate** (baseline-only vs +personalization).
- 🔴 Kill gate: if baseline agreement is already ≥ your data adds <2pts, personalization is noise → ship baseline-only, drop the learning story.

**Phase 4 — Train (gated, 2–3 days, needs GPU)**
- DoD: LoRA SFT on D2 → DPO on D3 → resolver beats prompt-only baseline on agreement + VACR.
- 🔴 Kill gate: trained model doesn't beat retrieval+steering → don't fine-tune; ship retrieval.

**Phase 5 — Live RLHF flywheel (2 days)**
- DoD: overrides auto-append to D3; weekly re-compose/retrain; SIGNALS dashboard (precedent-reuse ↑, override ↓) live.

## 8. Metrics — see SIGNALS.md
Leading (Learning → Thinking) predict lagging (Acting/VACR). North star = **Verified Autonomous Completion Rate**; "like-me" = **agreement rate**.

## 9. Risks
- Synthetic slop (mitigated: quality gate, drop-rate logged).
- Goodhart on tests (mitigated: HITL channel keeps it aligned to you, not just green checks).
- Over-engineering before proof (mitigated: kill gates at Phases 1/3/4).
- Premature fine-tuning (mitigated: model is the LAST step; retrieval/steering first).

## 10. File map (what exists vs TODO)
```
training/
  ARCHITECTURE.md        ← THIS doc (design + plan)        ✅
  DATA.md                ← data-first contract             ✅
  principles.yaml        ← L1 (canonical)                  ✅
  lifecycle.yaml         ← macro agentic SDLC              ✅
  packs/{tdd,spec-driven,security-first}.yaml              ✅
  compose.py             ← composer                        ✅
  build_dataset.py       ← D2/D3 extractor                 ✅
  best_practices.yaml    ← DUPLICATE → becomes adapter     ⛔ Phase 0
  adapters/<agent>.yaml  ← L2 bindings                     ⛔ Phase 2
  gen_synthetic.py       ← generator + quality gate        ⛔ Phase 1
  eval_agreement.py      ← "like-me" metric                ⛔ Phase 3
```
