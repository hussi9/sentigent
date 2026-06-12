"""Billing calculator — computes monthly invoice from cost telemetry.

Revenue model:
  - Success fee: 20% of verified savings_usd
  - Platform fee: 2% of total spend through the system (baseline cost)

Both are capped/floored in accordance with the agreed pricing schedule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUCCESS_FEE_RATE = 0.20   # 20% of verified savings
PLATFORM_FEE_RATE = 0.02  # 2% of total baseline spend

MIN_MONTHLY_USD = 0.0
MAX_SUCCESS_FEE_USD = 50_000.0  # safety cap per period


@dataclass
class BillingPeriod:
    year: int
    month: int
    agent_id: str
    org_id: str

    total_cost_usd: float = 0.0
    total_baseline_usd: float = 0.0
    total_savings_usd: float = 0.0
    total_tokens: int = 0
    event_count: int = 0

    success_fee_usd: float = 0.0
    platform_fee_usd: float = 0.0
    total_due_usd: float = 0.0
    savings_pct: float = 0.0


def compute_monthly_bill(
    events: list[dict[str, Any]],
    year: int,
    month: int,
    agent_id: str = "",
    org_id: str = "",
) -> BillingPeriod:
    """Compute the monthly bill from a list of cost event dicts.

    Args:
        events: List of cost event dicts (from CostEvent.to_dict())
        year: Billing year
        month: Billing month (1-12)
        agent_id: Agent identifier
        org_id: Org identifier

    Returns:
        BillingPeriod with all computed fields
    """
    period = BillingPeriod(
        year=year,
        month=month,
        agent_id=agent_id,
        org_id=org_id,
    )

    for ev in events:
        period.total_cost_usd += ev.get("cost_usd", 0.0)
        period.total_baseline_usd += ev.get("baseline_cost_usd", 0.0)
        period.total_savings_usd += ev.get("savings_usd", 0.0)
        period.total_tokens += (
            ev.get("input_tokens", 0) + ev.get("output_tokens", 0)
        )
        period.event_count += 1

    if period.total_baseline_usd > 0:
        period.savings_pct = round(
            100 * period.total_savings_usd / period.total_baseline_usd, 2
        )

    period.success_fee_usd = min(
        period.total_savings_usd * SUCCESS_FEE_RATE,
        MAX_SUCCESS_FEE_USD,
    )
    period.platform_fee_usd = period.total_baseline_usd * PLATFORM_FEE_RATE
    period.total_due_usd = max(
        period.success_fee_usd + period.platform_fee_usd,
        MIN_MONTHLY_USD,
    )

    # Round to cents
    period.total_cost_usd = round(period.total_cost_usd, 6)
    period.total_baseline_usd = round(period.total_baseline_usd, 6)
    period.total_savings_usd = round(period.total_savings_usd, 6)
    period.success_fee_usd = round(period.success_fee_usd, 6)
    period.platform_fee_usd = round(period.platform_fee_usd, 6)
    period.total_due_usd = round(period.total_due_usd, 6)

    return period


def format_bill(period: BillingPeriod) -> str:
    """Return a human-readable bill summary."""
    lines = [
        f"## Sentigent Invoice — {period.year}-{period.month:02d}",
        f"Agent: {period.agent_id}  |  Org: {period.org_id}",
        "",
        f"  API spend (actual):    ${period.total_cost_usd:>10.4f}",
        f"  API spend (baseline):  ${period.total_baseline_usd:>10.4f}",
        f"  Verified savings:      ${period.total_savings_usd:>10.4f}  ({period.savings_pct}%)",
        "",
        f"  Success fee (20%):     ${period.success_fee_usd:>10.4f}",
        f"  Platform fee (2%):     ${period.platform_fee_usd:>10.4f}",
        f"  ─────────────────────────────────────",
        f"  Total due:             ${period.total_due_usd:>10.4f}",
        "",
        f"  Events: {period.event_count}  |  Tokens: {period.total_tokens:,}",
    ]
    return "\n".join(lines)
