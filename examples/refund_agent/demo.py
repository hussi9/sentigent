"""The $50K Refund Demo — Sentigent's signature example.

This demo shows:
1. Day 1: An agent with baseline heuristics catches an anomalous refund
2. Learning: The agent processes many normal refunds and records outcomes
3. Day 180: The agent's judgment has evolved from operational experience

Run:
    python -m examples.refund_agent.demo
    # or
    python examples/refund_agent/demo.py
"""

import os
import sys
import tempfile

# Ensure sentigent package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sentigent import Sentigent


def main() -> None:
    # Use a temp DB so the demo is self-contained
    db_path = os.path.join(tempfile.gettempdir(), "sentigent_demo.db")

    print("=" * 70)
    print("  SENTIGENT DEMO: The $50K Refund")
    print("  The judgment layer that learns.")
    print("=" * 70)
    print()

    # Create a judgment layer with financial_ops profile
    judge = Sentigent(
        profile="financial_ops",
        agent_id="refund_agent_001",
        db_path=db_path,
    )

    # =========================================================================
    # PHASE 1: Day 1 — Baseline heuristics only
    # =========================================================================
    print("─" * 70)
    print("  PHASE 1: Day 1 — Agent uses baseline heuristics")
    print("─" * 70)
    print()

    # Normal refund — should PROCEED
    decision_normal = judge.evaluate(
        task="Process refund for $125",
        context={"amount": 125, "account_age_days": 400},
        agent_state={"step": "approve_refund", "confidence": 0.95},
    )
    print(f"  Refund $125 (normal):")
    print(f"    Action: {decision_normal.action.value}")
    print(f"    Signals: caution={decision_normal.signals.get('caution', 0):.2f}, "
          f"confidence={decision_normal.signals.get('confidence', 0):.2f}")
    print(f"    Reason: {decision_normal.reason}")
    print()

    # Anomalous refund — should ESCALATE
    decision_anomalous = judge.evaluate(
        task="Process refund for $50,000",
        context={"amount": 50_000, "account_age_days": 45},
        agent_state={"step": "approve_refund", "confidence": 0.88},
    )
    print(f"  Refund $50,000 (anomalous, new account):")
    print(f"    Action: {decision_anomalous.action.value}")
    print(f"    Signals: caution={decision_anomalous.signals.get('caution', 0):.2f}, "
          f"doubt={decision_anomalous.signals.get('doubt', 0):.2f}")
    print(f"    Reason: {decision_anomalous.reason}")
    print(f"    Judgment Score: {decision_anomalous.judgment_score:.1%}")
    print()

    # =========================================================================
    # PHASE 2: Simulate 100 operations with outcomes (training)
    # =========================================================================
    print("─" * 70)
    print("  PHASE 2: Simulating 100 operations with outcomes...")
    print("─" * 70)
    print()

    import random
    random.seed(42)

    for i in range(100):
        # Generate realistic refund amounts
        amount = random.lognormvariate(6.5, 1.2)  # median ~$650
        account_age = random.randint(30, 2000)
        confidence = random.uniform(0.7, 0.99)

        decision = judge.evaluate(
            task=f"Process refund for ${amount:.0f}",
            context={
                "amount": round(amount, 2),
                "account_age_days": account_age,
            },
            agent_state={
                "step": "approve_refund",
                "confidence": round(confidence, 2),
            },
        )

        # Simulate outcomes
        # High amounts on new accounts → usually fraud (incorrect to proceed)
        is_fraud = amount > 10_000 and account_age < 90 and random.random() < 0.85
        was_escalated = decision.action.value in ("escalate", "slow_down")

        if is_fraud and was_escalated:
            outcome = "correct"
        elif is_fraud and not was_escalated:
            outcome = "incorrect"
        elif not is_fraud and was_escalated and amount < 2000:
            outcome = "incorrect"  # False positive
        else:
            outcome = "correct"

        judge.record_outcome(
            trace_id=decision.trace_id,
            outcome=outcome,
            feedback=f"Simulated outcome for ${amount:.0f} refund",
        )

    print(f"  Processed 100 refunds with outcomes recorded.")
    print(f"  Agent is learning from operational experience...")
    print()

    # =========================================================================
    # PHASE 3: Day 180 — Learned judgment
    # =========================================================================
    print("─" * 70)
    print("  PHASE 3: After 100 operations — Agent has learned")
    print("─" * 70)
    print()

    # Same anomalous refund — now with learned context
    decision_learned = judge.evaluate(
        task="Process refund for $50,000",
        context={"amount": 50_000, "account_age_days": 45},
        agent_state={"step": "approve_refund", "confidence": 0.88},
    )
    print(f"  Refund $50,000 (same anomaly, but now with learned judgment):")
    print(f"    Action: {decision_learned.action.value}")
    print(f"    Signals: caution={decision_learned.signals.get('caution', 0):.2f}, "
          f"doubt={decision_learned.signals.get('doubt', 0):.2f}")
    print(f"    Reason: {decision_learned.reason}")
    print(f"    Judgment Score: {decision_learned.judgment_score:.1%}")
    print()

    # A moderate refund that's actually normal — should proceed more confidently now
    decision_moderate = judge.evaluate(
        task="Process refund for $800",
        context={"amount": 800, "account_age_days": 500},
        agent_state={"step": "approve_refund", "confidence": 0.92},
    )
    print(f"  Refund $800 (routine, established account):")
    print(f"    Action: {decision_moderate.action.value}")
    print(f"    Signals: confidence={decision_moderate.signals.get('confidence', 0):.2f}, "
          f"caution={decision_moderate.signals.get('caution', 0):.2f}")
    print(f"    Reason: {decision_moderate.reason}")
    print()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    print(f"  Total decisions: 102+")
    print(f"  Final judgment score: {judge.judgment_score:.1%}")
    print()
    print("  The agent's baselines evolved from industry defaults to")
    print("  learned patterns from its own operational experience.")
    print()
    print("  This is Sentigent: judgment that gets sharper every day.")
    print("=" * 70)

    # Clean up
    if os.path.exists(db_path):
        os.remove(db_path)


if __name__ == "__main__":
    main()
