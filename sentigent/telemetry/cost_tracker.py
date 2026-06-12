"""Cost tracker — captures model × token usage and computes savings vs baseline.

Emits CostEvent on every PostToolUse hook. Persists to SQLite via MemoryStore
and optionally to Supabase for cross-session aggregation.

MODEL_PRICES are per-million tokens (input/output). Source: Anthropic pricing page.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# USD per million tokens
MODEL_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-7":        {"input": 15.00, "output": 75.00},
    "claude-opus-4-5":        {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":      {"input":  3.00, "output": 15.00},
    "claude-sonnet-4-5":      {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-haiku-4-5":       {"input":  0.80, "output":  4.00},
    # Short aliases used by skill-router and callers
    "opus":    {"input": 15.00, "output": 75.00},
    "sonnet":  {"input":  3.00, "output": 15.00},
    "haiku":   {"input":  0.80, "output":  4.00},
}

# Baseline: assume every task would have used opus without routing
BASELINE_MODEL = "opus"


@dataclass
class CostEvent:
    trace_id: str
    agent_id: str
    model: str
    input_tokens: int
    output_tokens: int
    tool_name: str
    cost_usd: float = 0.0
    baseline_cost_usd: float = 0.0
    savings_usd: float = 0.0
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["meta"] = json.dumps(self.meta)
        return d


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a model call."""
    prices = MODEL_PRICES.get(model) or MODEL_PRICES.get("sonnet")
    return (
        prices["input"] * input_tokens / 1_000_000
        + prices["output"] * output_tokens / 1_000_000
    )


def compute_savings(model: str, input_tokens: int, output_tokens: int) -> float:
    """Savings vs always-opus baseline."""
    actual = compute_cost(model, input_tokens, output_tokens)
    baseline = compute_cost(BASELINE_MODEL, input_tokens, output_tokens)
    return max(0.0, baseline - actual)


def estimate_tokens(text: str) -> int:
    """Rough token count from characters (~4 chars/token). A real lower-bound
    proxy used when the hook payload carries no `usage` block (Claude Code's
    PostToolUse does not). Honest > the old all-zeros that made every cost
    $0.00 and every 'savings' fake. Callers flag meta.token_source='estimated'."""
    if not text:
        return 0
    return max(0, len(text) // 4)


def build_cost_event(
    trace_id: str,
    agent_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    tool_name: str = "",
    meta: dict[str, Any] | None = None,
) -> CostEvent:
    cost = compute_cost(model, input_tokens, output_tokens)
    baseline = compute_cost(BASELINE_MODEL, input_tokens, output_tokens)
    return CostEvent(
        trace_id=trace_id,
        agent_id=agent_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_name=tool_name,
        cost_usd=cost,
        baseline_cost_usd=baseline,
        savings_usd=max(0.0, baseline - cost),
        meta=meta or {},
    )


class CostTracker:
    """Records cost events and provides period summaries."""

    def __init__(self, agent_id: str, store: Any | None = None) -> None:
        self.agent_id = agent_id
        self._store = store
        self._events: list[CostEvent] = []

    def record(self, event: CostEvent) -> None:
        self._events.append(event)
        if self._store:
            try:
                self._store.insert_cost_event(event.to_dict())
            except Exception:
                pass

    def summary(self) -> dict[str, float]:
        """Return aggregate cost and savings across all recorded events."""
        total_cost = sum(e.cost_usd for e in self._events)
        total_baseline = sum(e.baseline_cost_usd for e in self._events)
        total_savings = sum(e.savings_usd for e in self._events)
        total_tokens = sum(e.input_tokens + e.output_tokens for e in self._events)
        return {
            "total_cost_usd": round(total_cost, 6),
            "total_baseline_usd": round(total_baseline, 6),
            "total_savings_usd": round(total_savings, 6),
            "savings_pct": round(
                100 * total_savings / total_baseline if total_baseline else 0.0, 2
            ),
            "total_tokens": total_tokens,
            "event_count": len(self._events),
        }

    def flush(self) -> list[dict[str, Any]]:
        """Return and clear the in-memory event buffer."""
        events = [e.to_dict() for e in self._events]
        self._events.clear()
        return events
