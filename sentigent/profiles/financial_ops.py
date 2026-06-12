"""Financial Operations profile — starter intuition for financial agents.

This profile provides day-1 baselines for agents handling:
- Refunds, chargebacks, payment processing
- Loan approvals, credit decisions
- Transaction monitoring, fraud detection

Values: financial_safety > compliance > accuracy > speed
"""

from sentigent.core.types import Profile, ValueHierarchy, WorldModel


def create_financial_ops_profile() -> Profile:
    """Create the financial_ops domain profile."""
    return Profile(
        name="financial_ops",
        description=(
            "Financial operations profile for agents handling transactions, "
            "refunds, approvals, and fraud detection. Prioritizes financial "
            "safety and compliance over speed."
        ),
        values=ValueHierarchy(
            values=[
                ("financial_safety", 1.0),  # Non-negotiable
                ("compliance", 0.95),
                ("accuracy", 0.8),
                ("customer_satisfaction", 0.6),
                ("speed", 0.4),
            ]
        ),
        world_model=WorldModel(
            baselines={
                # Transaction amounts
                "amount": {
                    "median": 847,
                    "mean": 1_250,
                    "std": 2_500,
                    "p5": 15,
                    "p25": 125,
                    "p75": 1_500,
                    "p95": 5_200,
                },
                "refund_amount": {
                    "median": 847,
                    "mean": 1_100,
                    "std": 2_000,
                    "p5": 10,
                    "p25": 95,
                    "p75": 1_200,
                    "p95": 4_500,
                },
                # Account characteristics
                "account_age_days": {
                    "median": 365,
                    "mean": 540,
                    "std": 400,
                    "p5": 30,
                    "p25": 120,
                    "p75": 730,
                    "p95": 1_825,
                },
                # Approval thresholds
                "approval_amount": {
                    "median": 5_000,
                    "mean": 12_000,
                    "std": 25_000,
                    "p5": 100,
                    "p25": 1_000,
                    "p75": 10_000,
                    "p95": 50_000,
                },
            }
        ),
        signal_thresholds={
            "caution_threshold": 2.0,  # z-score > 2 triggers caution
            "doubt_threshold": 0.6,    # compound confidence < 0.6
            "urgency_threshold": 0.8,  # urgency score > 0.8
            "confidence_fast_path": 0.92,  # high bar for financial fast-path
            "frustration_retries": 2,   # lower tolerance in financial ops
        },
    )
