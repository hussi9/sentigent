"""Close the skill-router → routing_seeds feedback loop.

``sentigent.scripts.migrate_skill_router_data`` imports skill-router's routing
DECISIONS (which skill/agent/model it chose for a prompt) into ``routing_seeds``.
That import is one-directional and one-shot: it never learns whether those routes
were any good.

This module imports the downstream OUTCOME. skill-router writes two log streams:

  * ``~/.claude/skill_router_log.jsonl`` — ``embedding-route`` events, each
    carrying a ``prompt_hash`` and the ``skill`` the router chose.
  * ``~/.claude/skill_usage.log`` — one TAB-separated line per Skill tool fire.

If the chosen skill was actually invoked shortly after the route fired, the route
was FOLLOWED; if it was never invoked, it was IGNORED. We aggregate follow/ignore
per ``prompt_hash`` and write the verdict back to ``routing_seeds.outcome`` — the
exact field :func:`sentigent.routing.matcher.match_seeds` already respects (it
excludes ``outcome='incorrect'``). A route the human consistently ignores stops
firing; a route they follow is reinforced.

Deterministic, no ML, no LLM. Conservative: a seed is demoted to ``incorrect``
only when it was routed at least :data:`MIN_OBSERVATIONS` times and followed zero
times, so thin or noisy signal can never kill a good seed. Fails open — any I/O
or store error is swallowed and the seed is left untouched.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROUTER_LOG_DEFAULT = Path.home() / ".claude" / "skill_router_log.jsonl"
USAGE_LOG_DEFAULT = Path.home() / ".claude" / "skill_usage.log"

# A Skill fire counts as "following" a route only if it lands within this many
# seconds after the route event. Mirrors skill-router's own learn-from-history.
FOLLOW_WINDOW_SEC = 120

# Never demote a seed to 'incorrect' on fewer than this many routed observations.
MIN_OBSERVATIONS = 2


# ── timestamp parsing ────────────────────────────────────────────────────────

def _parse_ts_iso(text: str) -> float | None:
    """Parse an ISO 'YYYY-MM-DDTHH:MM:SS' timestamp to epoch seconds."""
    try:
        return time.mktime(time.strptime(text, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _parse_ts_space(text: str) -> float | None:
    """Parse a 'YYYY-MM-DD HH:MM:SS' timestamp to epoch seconds."""
    try:
        return time.mktime(time.strptime(text.strip(), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


# ── log parsing ──────────────────────────────────────────────────────────────

def parse_route_events(log_path: Path, since: float = 0.0) -> list[dict[str, Any]]:
    """Return ``embedding-route`` events carrying both a prompt_hash and a skill.

    Each returned dict is ``{"prompt_hash", "skill", "ts"}`` with ``ts`` as epoch
    seconds. Non-route events, events missing a hash or skill, malformed lines,
    and events older than ``since`` are dropped.
    """
    if not Path(log_path).is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in Path(log_path).read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if event.get("type") != "embedding-route":
            continue
        prompt_hash = event.get("prompt_hash")
        skill = event.get("skill")
        if not prompt_hash or not skill:
            continue
        ts = _parse_ts_iso(str(event.get("ts", "")))
        if ts is None or ts < since:
            continue
        out.append({"prompt_hash": prompt_hash, "skill": skill, "ts": ts})
    out.sort(key=lambda e: e["ts"])
    return out


def parse_invocations(usage_path: Path, since: float = 0.0) -> list[dict[str, Any]]:
    """Return Skill tool fires as ``{"skill", "ts"}`` from skill_usage.log.

    Handles both the modern TAB-separated format and the legacy space-separated
    one. Malformed lines and fires older than ``since`` are dropped.
    """
    if not Path(usage_path).is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in Path(usage_path).read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            ts_str, _, skill = line.partition("\t")
        else:
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            ts_str, skill = parts
        skill = skill.strip()
        ts = _parse_ts_space(ts_str)
        if ts is None or not skill or ts < since:
            continue
        out.append({"skill": skill, "ts": ts})
    out.sort(key=lambda e: e["ts"])
    return out


# ── correlation + outcome policy ─────────────────────────────────────────────

def _was_followed(route: dict[str, Any], invocations: list[dict[str, Any]]) -> bool:
    """True iff the route's skill was invoked within the follow window after it.

    Conservative: any matching invocation in ``(ts, ts + FOLLOW_WINDOW_SEC]``
    counts, so we bias toward NOT demoting a seed that was ever followed.
    """
    lo = route["ts"]
    hi = lo + FOLLOW_WINDOW_SEC
    skill = route["skill"]
    for inv in invocations:
        if inv["ts"] <= lo:
            continue
        if inv["ts"] > hi:
            break  # invocations are sorted; nothing further is in-window
        if inv["skill"] == skill:
            return True
    return False


def classify(followed_count: int, total_count: int) -> str | None:
    """Map follow/total counts to a routing_seeds outcome, or None to leave it.

    * any genuine follow      → ``'correct'`` (reinforce)
    * >= MIN_OBSERVATIONS routes, zero follows → ``'incorrect'`` (demote/exclude)
    * otherwise (thin signal) → ``None`` (leave the seed's outcome unchanged)
    """
    if followed_count > 0:
        return "correct"
    if total_count >= MIN_OBSERVATIONS:
        return "incorrect"
    return None


def preview(
    route_events: list[dict[str, Any]],
    invocations: list[dict[str, Any]],
) -> dict[str, int]:
    """Read-only tally of what reconcile WOULD do — no store, no writes.

    Returns counts keyed ``would_reinforce`` / ``would_demote`` / ``thin`` over
    the distinct routed prompts. Used by dry-run paths (CLI + MCP tool).
    """
    tallies: dict[str, list[int]] = {}
    for route in route_events:
        pair = tallies.setdefault(route["prompt_hash"], [0, 0])
        pair[1] += 1
        if _was_followed(route, invocations):
            pair[0] += 1
    stats = {"seen": len(tallies), "would_reinforce": 0, "would_demote": 0, "thin": 0}
    for followed, total in tallies.values():
        target = classify(followed, total)
        if target == "correct":
            stats["would_reinforce"] += 1
        elif target == "incorrect":
            stats["would_demote"] += 1
        else:
            stats["thin"] += 1
    return stats


def reconcile_outcomes(
    store: Any,
    route_events: list[dict[str, Any]],
    invocations: list[dict[str, Any]],
) -> dict[str, int]:
    """Correlate routes vs invocations per prompt_hash and write back outcomes.

    Only seeds that already exist in ``routing_seeds`` are updated; an unknown
    prompt_hash (a route with no corresponding seed) is counted and skipped.
    Returns stats: ``seen`` (distinct hashes), ``reinforced``, ``demoted``,
    ``unchanged``, ``unknown``.
    """
    # Current outcome per known seed — lets us skip no-op writes and detect
    # unknown hashes without a query per event.
    try:
        current: dict[str, str] = {
            row["prompt_hash"]: (row.get("outcome") or "neutral")
            for row in store.get_all_routing_seeds_with_embeddings()
        }
    except Exception:
        current = {}

    # Aggregate follow/total per prompt_hash.
    tallies: dict[str, list[int]] = {}  # hash -> [followed, total]
    for route in route_events:
        h = route["prompt_hash"]
        pair = tallies.setdefault(h, [0, 0])
        pair[1] += 1
        if _was_followed(route, invocations):
            pair[0] += 1

    stats = {"seen": 0, "reinforced": 0, "demoted": 0, "unchanged": 0, "unknown": 0}
    for h, (followed, total) in tallies.items():
        stats["seen"] += 1
        if h not in current:
            stats["unknown"] += 1
            continue
        target = classify(followed, total)
        if target is None or target == current[h]:
            stats["unchanged"] += 1
            continue
        try:
            store.update_routing_seed_outcome(h, target)
        except Exception:
            stats["unchanged"] += 1
            continue
        stats["reinforced" if target == "correct" else "demoted"] += 1
    return stats


def run(
    store: Any,
    router_log: Path = ROUTER_LOG_DEFAULT,
    usage_log: Path = USAGE_LOG_DEFAULT,
    since: float = 0.0,
) -> dict[str, int]:
    """Parse both logs and reconcile outcomes against *store*. Returns stats."""
    routes = parse_route_events(router_log, since=since)
    invs = parse_invocations(usage_log, since=since)
    return reconcile_outcomes(store, routes, invs)
