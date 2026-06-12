"""One-time migration: import skill_router_log.jsonl into routing_seeds.

Sources usable records from embedding-route and embedding-skip events — the only
event types that carry prompt_hash + skill + path + confidence.

Usage:
    .venv/bin/python -m sentigent.scripts.migrate_skill_router_data
    .venv/bin/python -m sentigent.scripts.migrate_skill_router_data \\
        --log ~/.claude/skill_router_log.jsonl \\
        --agent default
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

PATH_TO_TASK_TYPE: dict[str, str] = {
    "BROKEN": "debug",
    "BUILD": "build",
    "OPERATE": "operate",
    "RESEARCH": "research",
}

_DEFAULT_LOG = Path.home() / ".claude" / "skill_router_log.jsonl"
_USABLE_TYPES = {"embedding-route", "embedding-skip"}


def parse_router_log(log_path: Path) -> list[dict[str, Any]]:
    """Return embedding-route and embedding-skip events that have a non-null skill."""
    records: list[dict[str, Any]] = []
    if not log_path.exists():
        return records
    seen_hashes: set[str] = set()
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") not in _USABLE_TYPES:
            continue
        skill = event.get("skill")
        prompt_hash = event.get("prompt_hash")
        if not skill or not prompt_hash:
            continue
        if prompt_hash in seen_hashes:
            continue
        seen_hashes.add(prompt_hash)
        path = event.get("path", "")
        records.append({
            "prompt_hash": prompt_hash,
            "prompt_text": _reconstruct_prompt(event),
            "task_type": PATH_TO_TASK_TYPE.get(path, "unknown"),
            "skill": skill,
            "agent": _skill_to_agent(skill),
            "model": "sonnet",
            "confidence": event.get("confidence") or event.get("winner_avg_sim") or 0.0,
            "avg_sim": event.get("avg_sim") or 0.0,
            "margin": event.get("margin") or 0.0,
            "neighbors": event.get("neighbors") or [],
            "outcome": "correct" if event.get("accepted") else "neutral",
        })
    return records


def _reconstruct_prompt(event: dict[str, Any]) -> str:
    """Use highest-sim neighbor prompt as proxy for the original prompt."""
    neighbors = event.get("neighbors") or []
    if neighbors:
        best = max(neighbors, key=lambda n: n.get("sim", 0.0))
        text = best.get("prompt", "")
        if text:
            return text
    return ""


def _skill_to_agent(skill: str) -> str:
    """Map skill name to a reasonable agent default."""
    lower = skill.lower()
    if "debug" in lower:
        return "debugger"
    if "frontend" in lower or "design" in lower:
        return "feature-dev:code-architect"
    if "test" in lower:
        return "test-runner"
    if "security" in lower:
        return "security-auditor"
    if "db" in lower or "database" in lower:
        return "db-expert"
    return "general-purpose"


def run_migration(
    store: Any,
    log_path: Path = _DEFAULT_LOG,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run the migration and return stats."""
    records = parse_router_log(log_path)
    inserted = 0
    skipped = 0

    _encode = None
    if not dry_run and records:
        try:
            from sentigent.routing.embeddings import encode as _encode  # type: ignore
        except Exception:
            _encode = None

    for rec in records:
        if dry_run:
            inserted += 1
            continue
        try:
            vec: list[float] = []
            if _encode and rec.get("prompt_text"):
                try:
                    vec = list(_encode(rec["prompt_text"]))
                except Exception:
                    vec = []
            store.insert_routing_seed(
                prompt_hash=rec["prompt_hash"],
                prompt_text=rec["prompt_text"],
                task_type=rec["task_type"],
                skill=rec["skill"],
                agent=rec["agent"],
                model=rec["model"],
                confidence=rec["confidence"],
                avg_sim=rec["avg_sim"],
                margin=rec["margin"],
                neighbors=rec["neighbors"],
                embedding=vec,
                outcome=rec["outcome"],
                source="skill_router_import",
            )
            inserted += 1
        except Exception:
            skipped += 1
    return {"total": len(records), "inserted": inserted, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate skill-router log into Sentigent routing_seeds")
    parser.add_argument("--log", default=str(_DEFAULT_LOG), help="Path to skill_router_log.jsonl")
    parser.add_argument("--agent", default="default", help="Agent ID for MemoryStore")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write")
    args = parser.parse_args()

    from sentigent.memory.store import MemoryStore
    store = MemoryStore(agent_id=args.agent, org_id="default")
    stats = run_migration(store, log_path=Path(args.log), dry_run=args.dry_run)
    print(f"Migration complete: {stats['inserted']} inserted, {stats['skipped']} skipped of {stats['total']} records")
    if args.dry_run:
        print("(dry-run — nothing written)")


if __name__ == "__main__":
    main()
