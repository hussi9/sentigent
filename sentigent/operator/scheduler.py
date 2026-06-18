"""Unattended scheduler — the cadence that keeps loops moving with no human present.

`loop_driver` knows how to push ONE loop forward; it does not know WHEN to wake up
or WHICH loops still need work. This module is the missing autopilot:

  1. scan LOOP_DIR for loops that still have pending work and aren't permanently stuck
  2. drive each of them ONE pass (one `drive` call → laps until done/blocked/max)
  3. sleep, repeat — on a fixed cadence (NEVER a busy-loop)

It is the glue between an OS scheduler (launchd/cron — see ops/com.sentigent.loop.plist)
and the loop driver. `tick()` is the unit a cron job runs once per invocation;
`run_forever()` is the long-lived daemon form. Everything is fail-soft and dependency-
injectable so the whole thing is deterministically testable with no real sleeping,
no real `claude`, and no real clock.

CLI:
  python -m sentigent.operator.scheduler tick   [--execute]
  python -m sentigent.operator.scheduler run    [--execute] [--interval 300] [--max-ticks N]
  python -m sentigent.operator.scheduler pending
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable, Iterator

from sentigent.operator import loop_driver

# A loop is "still has work" if any step is in one of these non-terminal states.
# done/skipped = the loop moved past it; failed/blocked = permanently stuck (a human
# must answer via loop_driver.answer before it's pending again) — neither is pickable.
_PENDING_STEP_STATES = {"pending"}
# Loop-level statuses the scheduler will NOT drive: terminal or human-gated.
_SKIP_LOOP_STATUS = {"done", "blocked", "error"}


def _loop_dir(loop_dir: Path | str | None) -> Path:
    """Resolve the directory to scan: explicit arg wins, else loop_driver.LOOP_DIR
    (read live, not at import — tests monkeypatch it the way the driver's own do)."""
    return Path(loop_dir) if loop_dir is not None else loop_driver.LOOP_DIR


def pending_loops(loop_dir: Path | str | None = None) -> list[str]:
    """Loop ids on disk with real work left: ≥1 pending step AND not in a terminal or
    permanently-blocked loop status. Sorted by created_at (oldest first → fair FIFO).

    Fail-soft: a missing dir, an unreadable/garbled JSON file, or a file missing its
    fields is simply skipped — the scheduler never crashes on a bad loop on disk.
    """
    d = _loop_dir(loop_dir)
    if not d.exists():
        return []
    rows: list[tuple[float, str]] = []
    for f in sorted(d.glob("loop_*.json")):
        try:
            st = json.loads(f.read_text())
        except Exception:
            continue
        loop_id = st.get("loop_id")
        if not loop_id or st.get("status") in _SKIP_LOOP_STATUS:
            continue
        steps = st.get("steps") or []
        has_work = any(
            (s.get("status") in _PENDING_STEP_STATES) for s in steps if isinstance(s, dict)
        )
        if has_work:
            rows.append((float(st.get("created_at", 0) or 0), loop_id))
    rows.sort(key=lambda r: r[0])
    return [loop_id for _, loop_id in rows]


def tick(
    *,
    execute: bool = False,
    loop_dir: Path | str | None = None,
    _driver: Callable[..., dict] | None = None,
) -> dict:
    """Drive every pending loop ONE pass. The atomic unit of unattended progress —
    this is what a cron/launchd invocation runs once.

    Returns {"driven": [loop_ids], "results": {id: summary_or_error}, "remaining": n}
    where `remaining` is how many loops still have work AFTER this pass (so a caller
    can decide whether to keep ticking). `_driver` is injectable (default
    loop_driver.drive) for tests. Each loop is driven in isolation: one loop raising
    is caught and recorded as {"error": ...} so the rest of the pass still runs.
    """
    drive = _driver or loop_driver.drive
    driven: list[str] = []
    results: dict[str, object] = {}
    for loop_id in pending_loops(loop_dir):
        driven.append(loop_id)
        try:
            results[loop_id] = drive(loop_id, execute=execute)
        except Exception as e:  # one bad loop must not abort the whole pass
            results[loop_id] = {"error": str(e)}
    remaining = len(pending_loops(loop_dir))
    return {"driven": driven, "results": results, "remaining": remaining}


def run_forever(
    interval_s: float,
    *,
    _sleep: Callable[[float], None] | None = None,
    _tick: Callable[..., dict] | None = None,
    max_ticks: int | None = None,
    execute: bool = False,
    loop_dir: Path | str | None = None,
) -> Iterator[dict]:
    """The unattended cadence: tick, sleep `interval_s`, repeat — forever in prod.

    This is a GENERATOR yielding each tick's result, so a caller (or a test) sees
    progress as it happens and can stop at any point. It NEVER busy-loops: every
    iteration blocks for `interval_s` via `_sleep` (default time.sleep) between ticks.
    Pair it with launchd/cron for OS-level supervision (see ops/com.sentigent.loop.plist)
    — that gives you restart-on-crash for free; this generator is the in-process form.

    Args:
      interval_s: seconds to sleep BETWEEN ticks (after each tick, before the next).
      _sleep:     injectable sleeper (tests pass a recorder that never really sleeps).
      _tick:      injectable tick fn (default `tick`), so tests stub the work.
      max_ticks:  stop after this many ticks; None = unbounded (the prod default).
      execute:    forwarded to tick → the driver (False = dry-run laps).
      loop_dir:   forwarded to tick (None = loop_driver.LOOP_DIR).
    """
    sleep = _sleep or time.sleep
    do_tick = _tick or tick
    n = 0
    while max_ticks is None or n < max_ticks:
        yield do_tick(execute=execute, loop_dir=loop_dir)
        n += 1
        if max_ticks is not None and n >= max_ticks:
            break  # don't sleep after the final tick — nothing follows it
        sleep(interval_s)


def seed_from_backlog(
    path: Path | str,
    *,
    _start: Callable[..., dict] | None = None,
) -> list[str]:
    """Optional: bootstrap loops from a `backlog.toml` of queued intentions.

    Format (each task becomes one loop):

        [[task]]
        goal = "ship the parser"
        steps = ["scaffold", "tokenizer", "tests"]
        verify = "pytest -q"          # optional → global verify_cmd
        cwd = "."                     # optional

    Returns the new loop_ids. Fail-soft: missing file, no TOML loader available
    (tomllib lands in 3.11), unreadable/garbled file, or no [[task]] entries → [].
    `_start` is injectable (default loop_driver.start) for tests.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        import tomllib  # py311+; fail-soft if older
    except Exception:
        return []
    try:
        data = tomllib.loads(p.read_text())
    except Exception:
        return []
    tasks = data.get("task")
    if not isinstance(tasks, list):
        return []
    start = _start or loop_driver.start
    new_ids: list[str] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        goal = t.get("goal")
        steps = t.get("steps")
        if not goal or not isinstance(steps, list) or not steps:
            continue
        kwargs: dict[str, object] = {}
        if t.get("verify"):
            kwargs["verify_cmd"] = str(t["verify"])
        cwd = t.get("cwd", ".")
        try:
            state = start(str(goal), list(steps), str(cwd), **kwargs)
            lid = state.get("loop_id")
            if lid:
                new_ids.append(lid)
        except Exception:
            continue  # one bad task never sinks the rest of the backlog
    return new_ids


# ── CLI ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="unattended loop scheduler (the autopilot cadence)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tick", help="drive every pending loop once")
    t.add_argument("--execute", action="store_true")

    r = sub.add_parser("run", help="tick forever on an interval (pair with launchd/cron)")
    r.add_argument("--execute", action="store_true")
    r.add_argument("--interval", type=float, default=300.0, help="seconds between ticks")
    r.add_argument("--max-ticks", type=int, default=None, help="stop after N ticks (default: forever)")

    sub.add_parser("pending", help="list loop ids that still have work")

    a = ap.parse_args()
    if a.cmd == "tick":
        res = tick(execute=a.execute)
        print(f"driven {len(res['driven'])} loop(s); {res['remaining']} still pending")
        for lid in res["driven"]:
            print(f"  {lid}")
    elif a.cmd == "run":
        for res in run_forever(a.interval, execute=a.execute, max_ticks=a.max_ticks):
            print(f"tick: driven {len(res['driven'])}, remaining {res['remaining']}")
    elif a.cmd == "pending":
        ids = pending_loops()
        print(f"{len(ids)} pending loop(s):")
        for lid in ids:
            print(f"  {lid}")


if __name__ == "__main__":
    main()
