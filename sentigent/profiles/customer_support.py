"""Customer Support profile — starter intuition for support agents.

This profile provides day-1 baselines for agents handling:
- Ticket triage and routing
- Customer escalation decisions
- Sentiment detection and response adjustment

Values: customer_satisfaction > accuracy > speed > cost
"""

from sentigent.core.types import Profile, ValueHierarchy, WorldModel


def create_customer_support_profile() -> Profile:
    """Create the customer_support domain profile."""
    return Profile(
        name="customer_support",
        description=(
            "Customer support profile for agents handling tickets, "
            "escalations, and customer interactions. Prioritizes customer "
            "satisfaction and accuracy over speed."
        ),
        values=ValueHierarchy(
            values=[
                ("customer_satisfaction", 1.0),
                ("accuracy", 0.85),
                ("speed", 0.7),
                ("cost_efficiency", 0.5),
            ]
        ),
        world_model=WorldModel(
            baselines={
                # Ticket metrics
                "ticket_priority": {
                    "median": 2,
                    "mean": 2.3,
                    "std": 1.0,
                    "p5": 1,
                    "p25": 1,
                    "p75": 3,
                    "p95": 4,
                },
                "customer_sentiment": {
                    "median": 0.5,
                    "mean": 0.45,
                    "std": 0.3,
                    "p5": -0.5,
                    "p25": 0.2,
                    "p75": 0.7,
                    "p95": 0.9,
                },
                "response_time_minutes": {
                    "median": 15,
                    "mean": 25,
                    "std": 30,
                    "p5": 2,
                    "p25": 5,
                    "p75": 30,
                    "p95": 120,
                },
                "escalation_rate": {
                    "median": 0.15,
                    "mean": 0.18,
                    "std": 0.1,
                    "p5": 0.02,
                    "p25": 0.08,
                    "p75": 0.25,
                    "p95": 0.45,
                },
            }
        ),
        signal_thresholds={
            "caution_threshold": 2.5,  # slightly more tolerant than financial
            "doubt_threshold": 0.55,
            "urgency_threshold": 0.75,
            "confidence_fast_path": 0.88,
            "frustration_retries": 3,
        },
    )
