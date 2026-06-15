# Steering Verdict — Sentigent Learning System

Date: 2026-06-13. Panel: Product Manager, Tech Lead, Product Designer, QA Lead
(independent reviews of `training/ARCHITECTURE.md` + supporting docs + the real data).

## Verdict: CHANGE (unanimous, 4/4)

Strategy and kill-gate discipline are sound. Execution as written would (a) train on
unverifiable synthetic data and (b) measure success with gameable metrics. Re-sequence
to prove the two unproven claims on existing data and fix the oracles before generating
or training anything. **No fine-tuning until the eval earns it.**

## The 3 blocking findings

1. **Quality gate is tautological.** `verify_intent: escalated` (and peers) check that
   the decision *label* appeared, not that the *judgment* was correct. A teacher told to
   produce an escalation always passes → the Phase-1 drop-rate kill gate never trips →
   we SFT on slop. FIX: each `verify` must include a discrimination test (reject a
   deliberately-wrong trajectory), a contrast/negative case, and an independent judge.
2. **Agreement metric is gameable.** Decisions are 96% `proceed`; a constant predictor
   scores 96% aggregate agreement. FIX: report per-class **balanced accuracy + confusion
   matrix**; gate on rare-class performance, never aggregate.
3. **Fine-tuning is unjustified at this data volume** (11 prefs, 1 negative, 4 classes).
   This is a retrieval + steering problem. DPO on rubric-derived pairs teaches "be the
   rubric," which retrieval already does. FIX: ship retrieval+steering; fine-tuning must
   beat it on held-out rare-class balanced accuracy to be built.

## Other required changes
- **Escalation recall** (false-negative: should-have-escalated, didn't, passed VACR) has
  no measurement path. Make it a Phase-1 pre-condition, not post-Phase-4.
- **Two parallel plans** (`ARCHITECTURE.md` phases vs `ROADMAP-PROVE-OR-KILL.md`) with
  different numbering → reconcile into ONE. (This itself is the "design got ahead of the
  decision" tell.)
- **Personalization moat depends on a missing UX artifact:** the override-and-teach
  surface is the only generator of D3 data. Add it (Designer).
- **L1.5 lifecycle / packs / adapters are operator IP, not progress on THIS initiative.**
  For the learning system, only L1 + adapters + data pipeline + eval matter.

## Re-sequenced execution (the single plan)

```
Gate −1  PROVE (existing data, no build):
   a. Agreement probe: brain-ON vs reset → per-class balanced accuracy   (cheap, local)
   b. SWE-bench Verified N=25 → Δ VACR                                   (needs Docker)
   → if both flat: ship verify+safety only; shelve the learning story.
Phase 0  dedupe best_practices→adapters/claude_code.yaml; merge ARCHITECTURE+ROADMAP.
Phase 1  EVAL HARNESS FIRST: golden trajectories (1/principle, human-labeled) +
         adversarial confusion-matrix per decision class + escalation-recall test;
         rewrite `verify` oracles to be discriminating WITH a known-bad rejection self-test.
Phase 2  gen_synthetic → quality-gated D2. DoD: gate rejects known-bad; rare classes
         filled with VERIFIED examples; drop-rate in sane band (alarm if <20% OR >70%);
         dedup/diversity check (no near-paraphrase padding).
Phase 3  Designer: session digest + provenance chips + override-and-teach
         (closes the trust wound AND generates D3).
Phase 4  Train ONLY if eval shows trained model beats retrieval+steering (same budget,
         held-out rare classes). Else ship retrieval+steering. DPO parked until D3 has
         hundreds of organic overrides.
```

## Per-member one-liners
- **PM:** Right strategy, over-built for its evidence. Run SWE-bench N=25 + the agreement
  probe first; let two numbers, not the architecture, authorize building. CHANGE.
- **Tech Lead:** Layering sound; the quality gate and agreement metric are tautologies
  that rubber-stamp slop; 11 pairs don't justify DPO. Ship retrieval; gate fine-tuning. CHANGE.
- **Designer:** Data plan GO, but not UX-ready — without the digest + provenance chips,
  personalization is invisible and the founder's trust complaint ships unfixed. CHANGE.
- **QA:** North-star good; verify oracles too weak for generation scale. Build golden +
  adversarial harness before any synthetic gen, or the drop-rate measures nothing. CHANGE.

## Decision required
Authorize **Gate −1 + Phase 1 (eval harness + real oracles)** as the next work. Everything
downstream (synthetic gen, training) stays frozen until those two numbers and the
discriminating gate exist.
