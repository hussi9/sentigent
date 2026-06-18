"""Tiny token-cost tracker for operator loops.

Closes the "token cost" watch-out with the smallest thing that works: a pure
pricing function plus a fail-soft per-loop JSONL ledger and a roll-up.

Pricing is a plain editable constant — these are round, public-ballpark list
prices (USD per 1M tokens) that YOU edit when rates change. They are deliberately
imprecise estimates, not invoiced truth; treat them as a budgeting signal only.

stdlib-only, typed, fail-soft: ``record`` never raises (a write error just flips
``logged`` to False), and ``summary`` degrades to zeros on any read trouble.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Pricing ────────────────────────────────────────────────────────────
#
# EDITABLE list-price estimates, USD per 1,000,000 tokens.
# {"in": <usd per 1M input tokens>, "out": <usd per 1M output tokens>}
#
# These are intentionally round, public-ballpark 2026 figures — NOT precise
# billing rates. Edit them to match your actual contract / current rate card.
# Unknown model ids fall back to the "default" entry below.
PRICING: dict[str, dict[str, float]] = {
    # Frontier / top tier — pricey, use sparingly.
    "claude-opus-4-8": {"in": 15.0, "out": 75.0},
    # Workhorse balanced tier.
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    # Cheap/fast tier.
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
    # Fallback for any unknown model id — a conservative mid-tier guess.
    "default": {"in": 3.0, "out": 15.0},
}

# Decimal places we round USD to. Sub-microdollar precision is noise.
_USD_DP = 6


def _default_cost_dir() -> Path:
    return Path.home() / ".sentigent" / "cost"


def cost_of(in_tokens: int, out_tokens: int, model: str = "default") -> float:
    """Estimate USD cost of a call. Pure; unknown model → 'default' pricing.

    Args:
        in_tokens: Input (prompt) token count.
        out_tokens: Output (completion) token count.
        model: Model id; falls back to PRICING["default"] if unknown.

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
    """
    price = PRICING.get(model, PRICING["default"])
    usd = (in_tokens * price["in"] + out_tokens * price["out"]) / 1_000_000
    return round(usd, _USD_DP)


def record(
    loop_id: str,
    *,
    in_tokens: int,
    out_tokens: int,
    model: str = "default",
    cost_dir: Any = None,
) -> dict[str, Any]:
    """Append a cost event to the per-loop JSONL ledger; return the event.

    Fail-soft: never raises. On any write error the returned event carries
    ``"logged": False`` so the caller can notice without crashing the loop.

    Args:
        loop_id: Loop identifier; names the log file ``<loop_id>.jsonl``.
        in_tokens: Input token count.
        out_tokens: Output token count.
        model: Model id (see PRICING).
        cost_dir: Directory for logs; default ``~/.sentigent/cost``.

    Returns:
        ``{loop_id, model, in_tokens, out_tokens, usd, logged}``.
    """
    event: dict[str, Any] = {
        "loop_id": loop_id,
        "model": model,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "usd": cost_of(in_tokens, out_tokens, model),
    }

    base = Path(cost_dir) if cost_dir is not None else _default_cost_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
        log_file = base / f"{loop_id}.jsonl"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        event["logged"] = True
    except (OSError, TypeError, ValueError):
        # Disk full, unwritable path, bad cost_dir — degrade, don't crash.
        event["logged"] = False

    return event


def _empty_summary() -> dict[str, Any]:
    return {
        "total_usd": 0.0,
        "in_tokens": 0,
        "out_tokens": 0,
        "by_model": {},
        "events": 0,
    }


def _read_events(log_file: Path) -> list[dict[str, Any]]:
    """Read one JSONL ledger; skip any malformed lines. Fail-soft → []."""
    events: list[dict[str, Any]] = []
    try:
        text = log_file.read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return events


def summary(loop_id: str | None = None, cost_dir: Any = None) -> dict[str, Any]:
    """Aggregate cost events. None loop_id → every ledger in ``cost_dir``.

    Fail-soft: any read trouble (missing dir, bad files) yields zeros for the
    affected ledgers rather than raising.

    Returns:
        ``{total_usd, in_tokens, out_tokens, by_model: {model: usd}, events}``.
    """
    out = _empty_summary()
    base = Path(cost_dir) if cost_dir is not None else _default_cost_dir()

    try:
        if loop_id is not None:
            files = [base / f"{loop_id}.jsonl"]
        else:
            files = sorted(base.glob("*.jsonl"))
    except OSError:
        return out

    by_model: dict[str, float] = {}
    for log_file in files:
        for ev in _read_events(log_file):
            in_t = int(ev.get("in_tokens", 0) or 0)
            out_t = int(ev.get("out_tokens", 0) or 0)
            usd = float(ev.get("usd", 0.0) or 0.0)
            model = str(ev.get("model", "default"))

            out["in_tokens"] += in_t
            out["out_tokens"] += out_t
            out["total_usd"] += usd
            out["events"] += 1
            by_model[model] = by_model.get(model, 0.0) + usd

    out["total_usd"] = round(out["total_usd"], _USD_DP)
    out["by_model"] = {m: round(v, _USD_DP) for m, v in by_model.items()}
    return out


__all__ = ["PRICING", "cost_of", "record", "summary"]
