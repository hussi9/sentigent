#!/usr/bin/env python3
"""Sentigent Loop — live proof (real local Gemma, no mocks).

Runs the real operate() control loop on a temp SQLite brain, with the Clone
Resolver backed by a live local model. Demonstrates the four dark-factory
properties an OSS reader should be able to reproduce:

  1. RESOLVE  — under COPILOT (would ask on EVERY step), the clone answers benign
                steps AS the seeded engineer and the line keeps moving. No page.
  2. HALT     — a force-push trips the inviolable policy wall; the clone never
                auto-clears a hard rule.
  3. COMPOUND — a human escalation answer is written back as a precedent and is
                retrievable for the next similar blocker.
  4. METRIC   — autonomy_rate = clone-resolved / (clone-resolved + asked).

Run: .venv/bin/python scripts/loop_proof.py
Requires Ollama with a gemma3 model pulled. ~1-2 min on gemma3:27b.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from sentigent.intelligence import local_llm
from sentigent.memory.store import MemoryStore
from sentigent.operator.operate import operate
from sentigent.operator.plan import parse_plan
from sentigent.operator.resolver import CloneResolver

PROFILE = {
    "summary": "Senior engineer. Ships fast and pragmatic. Tests before committing. "
               "Hates mock/demo data and hardcoded values — wants real solutions.",
    "preferences": ["small atomic commits", "TypeScript over JavaScript"],
    "coding_standards": ["run the relevant tests before committing", "no hardcoded data"],
    "never_do": ["force-push to main", "commit secrets", "hardcode data", "use mock data"],
}

BENIGN_PLAN = """# ship the helper
- [ ] run the existing unit test suite before committing the change
- [ ] add a TypeScript type annotation to the formatDate helper
- [ ] make one small atomic commit for the helper
"""

HARDFLOOR_PLAN = "# danger\n- [ ] git push --force origin main\n"


def banner(t: str) -> None:
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main() -> None:
    if not local_llm.llm_available():
        print("Ollama not reachable. Start it + pull a gemma3 model, then re-run.")
        return
    model = local_llm.resolver_model()
    print(f"Resolver model: {model}   (override with SENTIGENT_RESOLVER_MODEL)")
    print(f"Gate model: {local_llm.active_model()}")
    # Warm the resolver model so the first real call isn't a cold-load. Big models
    # (gemma3:27b ~17GB) can take minutes to load; a small one (gemma3:4b) is seconds.
    print("warming the resolver model ...", flush=True)
    _ = local_llm.generate('{"ok":1}', model=model, json_mode=True, timeout=600)
    print("warm.\n", flush=True)

    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(agent_id="proof", org_id="proof", db_path=Path(d) / "brain.db")
        store.save_operator_profile(json.dumps(PROFILE), source="llm")
        # Seed ONE precedent so the clone has prior context for one class of blocker.
        store.add_precedent("copilot", "regenerate the supabase types", "skip",
                            "I do that by hand later", source="seed")

        # ---- 1 + 4: RESOLVE under COPILOT (would normally ask on EVERY step) -----
        banner("PROOF 1 — Clone resolves benign steps AS the engineer (autonomy COPILOT)")
        print("COPILOT normally pauses for approval on EVERY step. Watch the clone "
              "answer them as the seeded engineer instead.\n")
        res = operate(store, parse_plan(BENIGN_PLAN), autonomy="copilot",
                      runner=None, execute=False)
        for o in res.outcomes:
            tag = ("🤖 CLONE-RESOLVED" if o.clone_resolved
                   else "🔔 ASKED YOU" if o.asked else o.status.upper())
            r = o.resolution or {}
            print(f"  step {o.idx}: {tag:<18} {o.description[:46]}")
            if r:
                print(f"            ↳ decision={r.get('decision')} "
                      f"conf={r.get('confidence')} — \"{r.get('rationale','')[:70]}\"")
        print(f"\n  RESULT: status={res.status}  clone_resolved={res.clone_resolves}  "
              f"asked={res.asks}  autonomy_rate={res.autonomy_rate:.0%}")

        # ---- 2: HALT on a hard rule --------------------------------------------
        banner("PROOF 2 — Hard rule (force-push) ALWAYS halts; never clone-resolved")
        res2 = operate(store, parse_plan(HARDFLOOR_PLAN), autonomy="trusted",
                       runner=None, execute=False)
        last = res2.outcomes[-1]
        print(f"  status={res2.status}  policy_wall={last.risk.get('policy_wall')}  "
              f"clone_resolved={last.clone_resolved}")
        print(f"  → {'PASS' if res2.status == 'waiting' and not last.clone_resolved else 'FAIL'}: "
              f"a force-push stopped the line for the human, as it must.")

        # ---- 3: COMPOUND via write-back ----------------------------------------
        banner("PROOF 3 — A human answer compounds into a retrievable precedent")
        eid = store.add_escalation(
            99, "delete the old migration files",
            context={"category": "risk_ceiling",
                     "clone_attempt": {"decision": "approve", "confidence": 0.55}}, risk=0.7)
        learned = store.learn_from_escalation_answer(eid, "skip")
        print(f"  human answered 'skip' → learned: {learned}")
        hits = CloneResolver(PROFILE, store=store).retrieve("delete old migration files",
                                                            "risk_ceiling")
        print(f"  next similar blocker retrieves: "
              f"{hits[0]['decision'] if hits else '(none)'} — "
              f"{'PASS' if hits and hits[0]['decision'] == 'skip' else 'FAIL'}")

        banner("SUMMARY")
        print(f"  • Clone answered {res.clone_resolves} blocker(s) as the engineer; "
              f"{res.asks} reached a human.")
        print(f"  • Autonomy rate this run: {res.autonomy_rate:.0%}")
        print("  • Hard rule halted the line. Human answer became a precedent.")
        print("  • All of the above ran on a LOCAL model — nothing left the machine.")


if __name__ == "__main__":
    main()
