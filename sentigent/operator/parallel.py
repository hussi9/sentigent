"""Parallel fan-out — drive MANY loops at once (roadmap X1, the missing sub-agent
concurrency).

`loop_driver.drive(loop_id)` advances one plan. When a vision splits into independent
sub-plans (separate loops), they should run *concurrently*, not one after another.
Each drive is subprocess/IO-bound (it shells out to `claude -p` and verifiers), so a
ThreadPoolExecutor is the right tool — threads release the GIL across those blocking
calls.

Design rules:
  • FAIL-SOFT per loop — if one loop's drive raises, record {"error": ...} for it and
    keep the others. `drive_many` itself never raises.
  • Injectable `_driver` — tests pass a fake so no real agents ever spawn. Defaults to
    `loop_driver.drive`.
  • Honest combined FAP — mean of per-loop FAP; an errored loop counts as 0.
"""
from __future__ import annotations

import concurrent.futures
from typing import Callable


def _default_driver() -> Callable:
    """The real driver, imported lazily so importing this module never drags in
    loop_driver's heavier deps unless a real run is requested."""
    from sentigent.operator import loop_driver
    return loop_driver.drive


def _fap_of(summary: dict) -> float:
    """Pull a 0..1 FAP from one loop's summary, fail-soft to 0.0.

    A summary may be either an already-computed result carrying a top-level "FAP"
    (e.g. a canned test summary) OR a raw loop_driver state (which has no top-level
    FAP — it must be derived from its steps via loop_driver.metrics). An error record
    or anything unrecognized scores 0.
    """
    if not isinstance(summary, dict) or "error" in summary:
        return 0.0
    if "FAP" in summary:
        try:
            return float(summary["FAP"])
        except (TypeError, ValueError):
            return 0.0
    if "steps" in summary:  # looks like a loop_driver state → derive it
        try:
            from sentigent.operator import loop_driver
            return float(loop_driver.metrics(summary).get("FAP", 0.0))
        except Exception:
            return 0.0
    return 0.0


def _is_completed(summary: dict) -> bool:
    """A loop is 'completed' when every one of its steps is done."""
    if not isinstance(summary, dict) or "error" in summary:
        return False
    steps = summary.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    return all(isinstance(s, dict) and s.get("status") == "done" for s in steps)


def combined_fap(summaries: list[dict]) -> float:
    """Mean FAP across summaries; empty → 0.0. Pure helper."""
    if not summaries:
        return 0.0
    return round(sum(_fap_of(s) for s in summaries) / len(summaries), 6)


def drive_many(loop_ids: list[str], *, execute: bool = False, max_workers: int = 4,
               _driver: Callable | None = None) -> dict:
    """Drive every loop_id concurrently and aggregate the results.

    Args:
        loop_ids: the loops to advance (each already created via loop_driver.start).
        execute: forwarded to the driver — False = dry-run laps, True = real agents.
        max_workers: thread pool size (each drive is subprocess/IO-bound).
        _driver: injectable drive callable for tests; defaults to loop_driver.drive.

    Returns:
        {
          "results": {loop_id: summary_or_{"error": str}},
          "combined_fap": float,   # mean per-loop FAP (errored loop = 0)
          "loops": int,            # number of loops driven
          "completed": int,        # loops whose every step is done
        }

    Fail-soft: a driver raising for one loop is captured as an {"error": ...} entry;
    the other loops still run and drive_many never raises.
    """
    driver = _driver or _default_driver()
    results: dict[str, dict] = {}

    if not loop_ids:
        return {"results": {}, "combined_fap": 0.0, "loops": 0, "completed": 0}

    workers = max(1, min(max_workers, len(loop_ids)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_id = {
            pool.submit(driver, lid, execute=execute): lid for lid in loop_ids
        }
        for fut in concurrent.futures.as_completed(future_to_id):
            lid = future_to_id[fut]
            try:
                results[lid] = fut.result()
            except Exception as e:  # fail-soft: one loop's blow-up never sinks the rest
                results[lid] = {"error": str(e)}

    ordered = [results[lid] for lid in loop_ids]
    return {
        "results": results,
        "combined_fap": combined_fap(ordered),
        "loops": len(loop_ids),
        "completed": sum(1 for s in ordered if _is_completed(s)),
    }
