# Steering Verdict — Prove-or-Kill Gap Closure (2026-06-16)

Panel: PM + Tech Lead + QA Lead (parallel review of the real capability audit).
Culture: brutal honesty. A capability is **PROVEN** only when a stranger can reproduce
the artifact behind it. Everything else is **BUILT** (code exists, unproven) or
**ROADMAP** (needs data/users we don't have yet).

## The gaps (where the product over-claims vs. proves)

| Gap | Verdict | Why |
|---|---|---|
| **G1 Clone live calibration** | **closeable now (code) — DONE this session** | The headline loop was calibration-**blind**: `loop_driver` never persisted the clone's attempt, so a human answer could never score it. Wired it. |
| **G2 FAP compounding** | **ROADMAP — defer honestly** | Needs ≥10 real `--execute` runs + a brain-off control. Synthesizing runs would be fabricated proof. Refuse. |
| **G3 Semantic memory** | **partially closeable** | Local vector retrieval already lives in `store.find_similar_episodes`. Real gaps: Supabase `match_episodes` RPC never queried; resolver precedent retrieval still keyword. (G3c/G3b next.) |
| **G4 Training quality gate + eval card** | **closeable** | `gen_synthetic.py`/`eval_agreement.py` exist but no gate fires and no `eval_card.md` is emitted; below N<50 gold pairs it must print ANECDOTAL. |
| **G5 Layer 3 collective** | **ROADMAP — defer honestly** | Opt-in path wired; needs ≥2 real orgs. Meaningless to "prove" solo. |
| **G6 Shipping to origin/main** | **closeable (PR, not force-push)** | Local branch has unrelated history to origin/main, but `resolver.py`/`store.py` are byte-identical; only `loop_driver.py` is a real reconcile. Ship via clean-clone + file-by-file + PR. |

## Done this session — G1 (the wedge)
- `loop_driver`: blocker path now derives a real per-kind **category** (`_blocker_category`),
  carries the clone's full **attempt** (decision + confidence) out of the killable child
  process, and on an `ask` **persists an escalation** with `clone_attempt` (`_persist_escalation`).
- New `loop_driver.answer(loop_id, decision)` + MCP **`loop_answer`**: a human answer runs
  `learn_from_escalation_answer` → **`record_calibration`** (scores the clone), closes the
  escalation, reopens the step, sets the loop back to running.
- Proven by `tests/test_loop_calibration.py` (real MemoryStore on a temp DB): a blocked
  loop persists the attempt; answering it records a calibration event. 24/24 loop tests green.
- **Honest status:** the wiring is PROVEN; *thresholds actually moving* still needs ≥3 real
  human answers per category accumulated in production → stays **BUILT** on the site until then.

## Deferred — stated publicly, not faked
- **G2 FAP compounding** and **G5 Layer 3** are **ROADMAP**: code-complete, proof-pending-data.
  The site's status board already labels them honestly.

## Next (code-closeable, in order)
G3c resolver embedding retrieval · G3b `backfill_embeddings.py` · G4 eval-card gate ·
G3a Supabase `match_episodes` RPC · G6 clean-clone PR to origin/main.
