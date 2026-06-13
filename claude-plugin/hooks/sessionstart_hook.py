#!/usr/bin/env python3
"""Sentigent SessionStart hook — injects team knowledge briefing at session start.

Runs at Claude Code session start. Pulls team_knowledge from Supabase and emits
a structured markdown briefing. Output is injected as session context by Claude Code.

Fails open silently — if Supabase is unavailable or table is empty, emits nothing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_dotenv() -> None:
    """Load SUPABASE_* vars from sentigent .env."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


def _detect_project_slug() -> str | None:
    """Detect current project from CLAUDE_PROJECT_PATH or cwd."""
    project_path = os.environ.get("CLAUDE_PROJECT_PATH") or os.environ.get("PWD", "")
    if not project_path:
        return None
    # Normalize: take the last directory component, lowercase, replace spaces with hyphens
    name = Path(project_path).name.lower().replace(" ", "-").replace("_", "-")
    return name or None


def _fetch_team_knowledge(org_id: str, project_slug: str | None) -> list[dict]:
    """Pull team_knowledge from Supabase for this org + project."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return []

    try:
        from supabase import create_client, Client
        db: Client = create_client(url, key)

        # Query global (project_slug IS NULL) + project-scoped rows
        result = db.table("team_knowledge").select(
            "type, content, confidence, project_slug, last_seen_at"
        ).eq("org_id", org_id).order("confidence", desc=True).limit(50).execute()

        rows = result.data or []

        # Filter: global rows always included, project rows only if slug matches
        filtered = []
        for row in rows:
            row_slug = row.get("project_slug")
            if row_slug is None:
                filtered.append(row)
            elif project_slug and row_slug == project_slug:
                filtered.append(row)

        return filtered
    except Exception:
        return []


def _fetch_recent_patterns(org_id: str) -> list[dict]:
    """Pull top org_patterns by success_rate from existing table."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return []

    try:
        from supabase import create_client, Client
        db: Client = create_client(url, key)

        result = db.table("org_patterns").select(
            "pattern_type, description, success_rate, sample_size"
        ).eq("org_id", org_id).gte("sample_size", 3).order(
            "success_rate", desc=True
        ).limit(5).execute()

        return result.data or []
    except Exception:
        return []


def _format_briefing(
    project_slug: str | None,
    knowledge: list[dict],
    patterns: list[dict],
) -> str:
    """Format team knowledge as a structured markdown briefing."""
    if not knowledge and not patterns:
        return ""

    # Group by type
    by_type: dict[str, list[str]] = {
        "convention": [],
        "decision": [],
        "pitfall": [],
        "pattern": [],
    }
    for row in knowledge:
        t = row.get("type", "convention")
        content = row.get("content", "").strip()
        if content and t in by_type:
            by_type[t].append(content)

    # Build sections
    sections: list[str] = []

    label = project_slug or "global"
    sections.append(f"## Sentigent Team Briefing — {label}")
    sections.append("")

    if by_type["convention"]:
        sections.append("### Team Conventions")
        for item in by_type["convention"]:
            sections.append(f"- {item}")
        sections.append("")

    if by_type["decision"]:
        sections.append("### Recent Decisions")
        for item in by_type["decision"]:
            sections.append(f"- {item}")
        sections.append("")

    if by_type["pitfall"]:
        sections.append("### Known Pitfalls")
        for item in by_type["pitfall"]:
            sections.append(f"- {item}")
        sections.append("")

    if by_type["pattern"]:
        sections.append("### Learned Patterns")
        for item in by_type["pattern"]:
            sections.append(f"- {item}")
        sections.append("")

    if patterns:
        sections.append("### High-Confidence Org Patterns")
        for p in patterns:
            rate = p.get("success_rate", 0)
            desc = p.get("description", "").strip()
            if desc:
                sections.append(f"- {desc} (confidence: {rate:.0%})")
        sections.append("")

    result = "\n".join(sections).strip()
    return result if len(result) > 50 else ""


def _clone_briefing() -> str:
    """The clone speaks: a fast, local-only 'here's your clone' briefing.
    Reads SQLite only — no LLM, no network. Fail-soft to ''."""
    try:
        # Make the package importable when run as a standalone hook script.
        repo = Path(__file__).resolve().parent.parent.parent
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from sentigent.core.briefing import (
            build_clone_briefing,
            build_engagement_line,
        )
        from sentigent.memory.store import MemoryStore

        agent_id = os.environ.get("SENTIGENT_AGENT_ID", "claude_code")
        org_id = os.environ.get("SENTIGENT_ORG_ID", "default")
        store = MemoryStore(agent_id=agent_id, org_id=org_id)
        # Engagement line first — the direct "yes, it's on and here's what it's
        # doing" — then the clone briefing. Either may be '' (fail-soft).
        parts = [build_engagement_line(store), build_clone_briefing(store)]
        return "\n\n".join(p for p in parts if p)
    except Exception:
        return ""


def main() -> None:
    _load_dotenv()

    # 1) The clone greets you (local, fast, always — the primary in-session surface).
    clone = _clone_briefing()
    if clone:
        print(clone)
        print()

    # 2) Team knowledge briefing (optional, Supabase — fail-soft if unavailable).
    org_id = os.environ.get("SENTIGENT_ORG_ID", "")
    if not org_id:
        return

    project_slug = _detect_project_slug()

    # Read session data from stdin (Claude Code sends JSON payload)
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            # Claude Code may provide the project path in the payload
            if "cwd" in data and not os.environ.get("CLAUDE_PROJECT_PATH"):
                os.environ["CLAUDE_PROJECT_PATH"] = data["cwd"]
                project_slug = _detect_project_slug()
    except Exception:
        pass

    knowledge = _fetch_team_knowledge(org_id, project_slug)
    patterns = _fetch_recent_patterns(org_id)

    briefing = _format_briefing(project_slug, knowledge, patterns)
    if briefing:
        print(briefing)


if __name__ == "__main__":
    main()
