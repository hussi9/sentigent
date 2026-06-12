"""Sync Manager — synchronizes Layer 1 (local SQLite) with Layer 2 (Supabase).

Uses supabase-py directly — no custom HTTP server needed.
Sync is non-blocking and failure-tolerant: local operation always works.

Layer 2: organizational intelligence — episodes from all agents in your org
         are stored in Supabase and used to compute shared baselines.
Layer 3: collective intelligence — cross-org patterns stored locally in SQLite.
         Opt-in per profile; patterns can be shared when a cloud sync is configured.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _get_supabase_client():
    """Create a supabase-py client from environment variables."""
    try:
        from supabase import create_client
    except ImportError:
        raise RuntimeError(
            "supabase-py not installed. Run: pip install supabase"
        )

    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL environment variable not set")

    # Service role key bypasses RLS — needed for agent writes
    key = os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY",
        os.environ.get("SUPABASE_ANON_KEY", ""),
    )
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY not set")

    return create_client(url, key)


def _resolve_org_id(client, org_id: str) -> str:
    """Resolve org_id to a Supabase UUID.

    Priority:
    1. If org_id is already a valid UUID, use it directly.
    2. If SENTIGENT_ORG_ID env var is set, use that.
    3. Look up the org by slug in the organizations table.
    4. Look up the org via the SENTIGENT_API_KEY hash in api_keys table.

    Raises RuntimeError if org cannot be resolved.
    """
    import re

    # Already a UUID?
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if re.match(uuid_pattern, org_id, re.IGNORECASE):
        return org_id

    # Explicit env override — only if it's a UUID (slugs fall through to lookup below)
    env_org_id = os.environ.get("SENTIGENT_ORG_ID")
    if env_org_id and re.match(uuid_pattern, env_org_id, re.IGNORECASE):
        return env_org_id

    # Look up by slug (try passed org_id first, then env slug if different)
    slugs_to_try = [org_id]
    if env_org_id and env_org_id != org_id:
        slugs_to_try.append(env_org_id)
    for slug in slugs_to_try:
        try:
            result = (
                client.table("organizations")
                .select("id")
                .eq("slug", slug)
                .single()
                .execute()
            )
            if result.data:
                resolved = result.data["id"]
                logger.debug("Resolved org slug '%s' → %s", slug, resolved)
                return resolved
        except Exception:
            pass

    # Last resort: look up via API key in env
    api_key = os.environ.get("SENTIGENT_API_KEY")
    if api_key:
        try:
            import hashlib
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            result = (
                client.table("api_keys")
                .select("org_id")
                .eq("key_hash", key_hash)
                .eq("is_active", True)
                .single()
                .execute()
            )
            if result.data:
                return result.data["org_id"]
        except Exception:
            pass

    raise RuntimeError(
        f"Cannot resolve org_id '{org_id}'. "
        "Set SENTIGENT_ORG_ID env var or use a valid UUID / org slug."
    )


class SyncManager:
    """Manages synchronization between local SQLite and Supabase (Layer 2)."""

    def __init__(
        self,
        org_id: str,
        agent_id: str,
        batch_size: int = 100,
        db_path: str | None = None,
    ) -> None:
        self.org_id = org_id
        self._raw_org_id = org_id  # slug or UUID as given
        self.agent_id = agent_id
        self.batch_size = batch_size
        self._client = None  # lazy init
        self._supabase_org_id: str | None = None  # resolved on first use
        self._last_sync_at: datetime | None = None
        # Layer 3 uses local SQLite — no cloud dependency
        self._db_path = db_path or os.path.expanduser(
            f"~/.sentigent/memory_{agent_id}.db"
        )
        self._local_conn: sqlite3.Connection | None = None

    def _get_local_conn(self) -> sqlite3.Connection:
        """Open (and init) the local SQLite connection for Layer 3 data."""
        if self._local_conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._local_conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local_conn.row_factory = sqlite3.Row
            self._init_layer3_tables(self._local_conn)
        return self._local_conn

    @staticmethod
    def _init_layer3_tables(conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS collective_opt_ins (
                org_id       TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                opted_in     INTEGER NOT NULL DEFAULT 0,
                opted_in_at  TEXT,
                opted_out_at TEXT,
                PRIMARY KEY (org_id, profile_name)
            );
            CREATE TABLE IF NOT EXISTS layer3_shared_patterns (
                pattern_name           TEXT PRIMARY KEY,
                learned_action         TEXT NOT NULL,
                success_rate           REAL NOT NULL,
                sample_size            INTEGER NOT NULL,
                contributing_org_count INTEGER NOT NULL DEFAULT 1,
                industry_tags          TEXT NOT NULL DEFAULT '[]',
                last_reinforced        TEXT NOT NULL
            );
        """)

    @property
    def supabase_org_id(self) -> str:
        """Lazily resolve the Supabase org UUID on first access."""
        if self._supabase_org_id is None:
            self._supabase_org_id = _resolve_org_id(self._get_client(), self._raw_org_id)
        return self._supabase_org_id

    def _get_client(self):
        if self._client is None:
            self._client = _get_supabase_client()
        return self._client

    def _set_org_context(self, client) -> None:
        """Set the RLS org context so queries are automatically scoped.

        This calls the set_org_context() Postgres function which sets
        app.current_org_id for the current session, enabling RLS policies
        to enforce tenant isolation.

        Falls back silently if the RLS migration hasn't been run yet.
        """
        try:
            client.rpc("set_org_context", {"p_org_id": self.supabase_org_id}).execute()
        except Exception:
            # RLS migration 004 not yet run — safe to ignore, queries still
            # include org_id in WHERE clauses for application-level isolation.
            pass

    def push_episodes(self, episodes: list[dict[str, Any]]) -> dict[str, Any]:
        """Push local episodes to Supabase (Layer 1 → Layer 2).

        Uses upsert on (org_id, trace_id) so re-syncing is safe.
        """
        if not episodes:
            return {"synced": 0, "failed": 0}

        client = self._get_client()
        self._set_org_context(client)
        synced = 0
        failed = 0

        # Phase 5: Pre-compute batch embeddings for all episodes (best-effort)
        episode_embeddings: dict[str, list[float]] = {}
        try:
            from sentigent.core.embedder import get_embedder
            embedder = get_embedder()
            if embedder:
                tasks = [ep.get("task", "") for ep in episodes if ep.get("trace_id")]
                trace_ids = [ep["trace_id"] for ep in episodes if ep.get("trace_id")]
                vecs = embedder.encode_batch(tasks)
                episode_embeddings = dict(zip(trace_ids, vecs))
        except Exception:
            pass  # embeddings are always optional

        for i in range(0, len(episodes), self.batch_size):
            batch = episodes[i: i + self.batch_size]
            rows = [
                {
                    "org_id": self.supabase_org_id,
                    "agent_id": ep.get("agent_id", self.agent_id),
                    "trace_id": ep["trace_id"],
                    "task": ep.get("task", ""),
                    "context": ep.get("context") or {},
                    "agent_state": ep.get("agent_state") or {},
                    "signals": ep.get("signals") or {},
                    "decision": ep.get("decision", ""),
                    "reason": ep.get("reason", ""),
                    "confidence_at_decision": ep.get("confidence", 0.5),
                    "outcome": ep.get("outcome"),
                    "outcome_feedback": ep.get("feedback"),
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    # Phase 2: task context
                    **(
                        {"task_id": (ep.get("context") or {}).get("_task_id")}
                        if isinstance(ep.get("context"), dict) and (ep.get("context") or {}).get("_task_id")
                        else {}
                    ),
                    # Phase 5: semantic embedding (pgvector format: list of floats)
                    **(
                        {"embedding": episode_embeddings[ep["trace_id"]]}
                        if ep.get("trace_id") in episode_embeddings and episode_embeddings[ep["trace_id"]]
                        else {}
                    ),
                }
                for ep in batch
                if ep.get("trace_id")  # skip any without a trace_id
            ]

            if not rows:
                continue

            try:
                client.table("synced_episodes").upsert(
                    rows,
                    on_conflict="org_id,trace_id",
                ).execute()
                synced += len(rows)
                logger.debug("Synced %d episodes to Supabase", len(rows))
            except Exception as exc:
                failed += len(rows)
                logger.warning("Failed to sync batch: %s", exc)

        self._last_sync_at = datetime.now(timezone.utc)

        # After a successful sync, feed episodes into the org world model.
        # This is how the world model learns from real agent activity automatically.
        # Fails silently — world model enrichment is never blocking.
        if synced > 0:
            try:
                self._update_world_model(client, episodes)
            except Exception as wm_exc:
                logger.debug("World model update skipped: %s", wm_exc)

        return {
            "synced": synced,
            "failed": failed,
            "synced_at": self._last_sync_at.isoformat(),
        }

    def _update_world_model(self, client: Any, episodes: list[dict[str, Any]]) -> None:
        """Feed synced episodes into the org world model (non-blocking)."""
        from sentigent.memory.world_model import WorldModelBuilder
        builder = WorldModelBuilder(client, self.supabase_org_id)
        builder.process_episodes(episodes)
        counts = builder.flush()
        logger.debug("World model updated from %d episodes: %s", len(episodes), counts)

    def push_pattern(self, pattern: dict[str, Any], profile_name: str) -> bool:
        """Push a learned pattern to Supabase org_patterns (Layer 2)."""
        try:
            client = self._get_client()
            self._set_org_context(client)
            client.table("org_patterns").upsert(
                {
                    "org_id": self.supabase_org_id,
                    "profile_name": profile_name,
                    "pattern_name": pattern["pattern_name"],
                    "condition": pattern.get("condition", {}),
                    "learned_action": pattern["learned_action"],
                    "success_rate": pattern.get("success_rate", 0),
                    "sample_size": pattern.get("sample_size", 0),
                    "contributing_agents": [self.agent_id],
                    "last_reinforced": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="org_id,profile_name,pattern_name",
            ).execute()
            return True
        except Exception as exc:
            logger.warning("Failed to push pattern %s: %s", pattern.get("pattern_name"), exc)
            return False

    def pull_org_baselines(self, profile_name: str) -> list[dict[str, Any]]:
        """Pull org-wide aggregated baselines back to local (Layer 2 → Layer 1)."""
        try:
            client = self._get_client()
            self._set_org_context(client)
            result = (
                client.table("org_baselines")
                .select("metric_name,median,mean,std,p5,p25,p75,p95,min_observed,max_observed,sample_size")
                .eq("org_id", self.supabase_org_id)
                .eq("profile_name", profile_name)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.warning("Failed to pull org baselines: %s", exc)
            return []

    def pull_org_patterns(self, profile_name: str) -> list[dict[str, Any]]:
        """Pull org-wide learned patterns (Layer 2 → Layer 1)."""
        try:
            client = self._get_client()
            self._set_org_context(client)
            result = (
                client.table("org_patterns")
                .select("pattern_name,condition,learned_action,success_rate,sample_size")
                .eq("org_id", self.supabase_org_id)
                .eq("profile_name", profile_name)
                .eq("is_active", True)
                .gte("success_rate", 0.8)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.warning("Failed to pull org patterns: %s", exc)
            return []

    def trigger_org_baseline_recompute(self, profile_name: str) -> bool:
        """Trigger Supabase to recompute org baselines from all synced episodes."""
        try:
            client = self._get_client()
            client.rpc(
                "compute_org_baselines",
                {"p_org_id": self.supabase_org_id, "p_profile_name": profile_name},
            ).execute()
            logger.info("Triggered org baseline recompute for profile=%s", profile_name)
            return True
        except Exception as exc:
            logger.warning("Failed to trigger baseline recompute: %s", exc)
            return False

    def get_judgment_score(self) -> dict[str, Any]:
        """Get judgment score for this agent from Supabase."""
        try:
            client = self._get_client()
            result = client.rpc(
                "get_judgment_score",
                {"p_org_id": self.supabase_org_id, "p_agent_id": self.agent_id},
            ).execute()
            if result.data:
                return result.data[0]
            return {"total_decisions": 0, "correct_decisions": 0, "score": 0}
        except Exception as exc:
            logger.warning("Failed to get judgment score: %s", exc)
            return {}

    # ── Layer 3: Cross-org collective intelligence ─────────────────────────────

    def set_layer3_opt_in(self, profile_name: str, opted_in: bool) -> bool:
        """Opt this org in or out of Layer 3 collective intelligence (stored locally in SQLite)."""
        try:
            conn = self._get_local_conn()
            now = datetime.now(timezone.utc).isoformat()
            opted_in_at = now if opted_in else None
            opted_out_at = None if opted_in else now
            conn.execute(
                """
                INSERT INTO collective_opt_ins (org_id, profile_name, opted_in, opted_in_at, opted_out_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(org_id, profile_name) DO UPDATE SET
                    opted_in = excluded.opted_in,
                    opted_in_at = CASE WHEN excluded.opted_in THEN excluded.opted_in_at ELSE opted_in_at END,
                    opted_out_at = CASE WHEN NOT excluded.opted_in THEN excluded.opted_out_at ELSE opted_out_at END
                """,
                (self.org_id, profile_name, int(opted_in), opted_in_at, opted_out_at),
            )
            conn.commit()
            logger.info(
                "Layer 3 opt-%s for org=%s profile=%s",
                "in" if opted_in else "out",
                self.org_id,
                profile_name,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to set layer3 opt-in: %s", exc)
            return False

    def get_layer3_opt_in(self, profile_name: str) -> bool:
        """Check if this org is opted into Layer 3 for the given profile."""
        try:
            conn = self._get_local_conn()
            row = conn.execute(
                "SELECT opted_in FROM collective_opt_ins WHERE org_id=? AND profile_name=?",
                (self.org_id, profile_name),
            ).fetchone()
            return bool(row["opted_in"]) if row else False
        except Exception as exc:
            logger.warning("Failed to check layer3 opt-in: %s", exc)
            return False

    def contribute_to_layer3(
        self,
        patterns: list[dict[str, Any]],
        profile_name: str,
        industry_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store high-confidence learned patterns in the local Layer 3 pool.

        Only contributes if opted in. When a pattern already exists, its
        success_rate is updated as a weighted average.

        Returns:
            {"contributed": N, "skipped": N, "opted_in": bool}
        """
        import json as _json

        opted_in = self.get_layer3_opt_in(profile_name)
        if not opted_in:
            return {"contributed": 0, "skipped": len(patterns), "opted_in": False}

        conn = self._get_local_conn()
        contributed = 0
        skipped = 0
        tags_json = _json.dumps(industry_tags or [])
        now = datetime.now(timezone.utc).isoformat()

        for p in patterns:
            if p.get("success_rate", 0) < 0.85 or p.get("sample_size", 0) < 5:
                skipped += 1
                continue
            try:
                pattern_name = p["pattern_name"]
                new_rate = p["success_rate"]
                new_size = p["sample_size"]
                existing = conn.execute(
                    "SELECT success_rate, sample_size, contributing_org_count FROM layer3_shared_patterns WHERE pattern_name=?",
                    (pattern_name,),
                ).fetchone()
                if existing:
                    old_size = existing["sample_size"] or 0
                    old_count = existing["contributing_org_count"] or 1
                    merged_size = old_size + new_size
                    merged_rate = (
                        (existing["success_rate"] * old_size + new_rate * new_size) / merged_size
                        if merged_size > 0
                        else new_rate
                    )
                    conn.execute(
                        """UPDATE layer3_shared_patterns SET
                            success_rate=?, sample_size=?, contributing_org_count=?,
                            industry_tags=?, last_reinforced=?
                           WHERE pattern_name=?""",
                        (round(merged_rate, 4), merged_size, old_count + 1, tags_json, now, pattern_name),
                    )
                else:
                    conn.execute(
                        """INSERT INTO layer3_shared_patterns
                            (pattern_name, learned_action, success_rate, sample_size,
                             contributing_org_count, industry_tags, last_reinforced)
                           VALUES (?, ?, ?, ?, 1, ?, ?)""",
                        (pattern_name, p["learned_action"], round(new_rate, 4), new_size, tags_json, now),
                    )
                contributed += 1
            except Exception as exc:
                logger.warning("Failed to contribute pattern %s: %s", p.get("pattern_name"), exc)
                skipped += 1

        conn.commit()
        logger.info("Layer 3 contribution: %d contributed, %d skipped for profile=%s", contributed, skipped, profile_name)
        return {"contributed": contributed, "skipped": skipped, "opted_in": True}

    def pull_layer3_patterns(
        self,
        min_success_rate: float = 0.85,
        min_orgs: int = 1,
        industry_tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Pull collective patterns from the local Layer 3 pool.

        Args:
            min_success_rate: Minimum success rate to include (default 0.85)
            min_orgs: Minimum contributing_org_count (default 1)
            industry_tags: Optional filter by industry tag substring

        Returns:
            List of pattern dicts sorted by success_rate descending.
        """
        import json as _json

        try:
            conn = self._get_local_conn()
            rows = conn.execute(
                """SELECT pattern_name, learned_action, success_rate, sample_size,
                          contributing_org_count, industry_tags
                   FROM layer3_shared_patterns
                   WHERE success_rate >= ? AND contributing_org_count >= ?
                   ORDER BY success_rate DESC LIMIT 100""",
                (min_success_rate, min_orgs),
            ).fetchall()
            result = []
            for r in rows:
                tags = _json.loads(r["industry_tags"] or "[]")
                if industry_tags and not any(t in tags for t in industry_tags):
                    continue
                result.append({
                    "pattern_name": r["pattern_name"],
                    "learned_action": r["learned_action"],
                    "success_rate": r["success_rate"],
                    "sample_size": r["sample_size"],
                    "contributing_org_count": r["contributing_org_count"],
                    "industry_tags": tags,
                })
            logger.debug("Pulled %d layer3 patterns", len(result))
            return result
        except Exception as exc:
            logger.warning("Failed to pull layer3 patterns: %s", exc)
            return []

    def get_layer3_status(self) -> dict[str, Any]:
        """Get Layer 3 collective intelligence status for this org."""
        try:
            conn = self._get_local_conn()
            opt_in_rows = conn.execute(
                "SELECT profile_name FROM collective_opt_ins WHERE org_id=? AND opted_in=1",
                (self.org_id,),
            ).fetchall()
            pool_rows = conn.execute(
                "SELECT success_rate, contributing_org_count FROM layer3_shared_patterns",
            ).fetchall()
            pool = list(pool_rows)
            return {
                "opted_in_profiles": [r["profile_name"] for r in opt_in_rows],
                "pool_size": len(pool),
                "pool_avg_success_rate": (
                    sum(p["success_rate"] for p in pool) / len(pool) if pool else 0
                ),
                "multi_org_patterns": sum(1 for p in pool if p["contributing_org_count"] > 1),
            }
        except Exception as exc:
            logger.warning("Failed to get layer3 status: %s", exc)
            return {"opted_in_profiles": [], "pool_size": 0}

    def push_setup_patterns(
        self, patterns: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Push anonymized setup change patterns to Supabase org_setup_patterns table.

        Args:
            patterns: List of formatted change dicts from SetupSyncManager.format_for_push().

        Returns:
            Dict with 'pushed' and 'failed' counts.
        """
        if not patterns:
            return {"pushed": 0, "failed": 0}

        pushed = 0
        failed = 0
        try:
            client = self._get_client()
            self._set_org_context(client)
            for p in patterns:
                try:
                    client.table("org_setup_patterns").upsert({
                        "org_id": self.supabase_org_id,
                        "source_agent_id": p.get("source_agent_id", "unknown"),
                        "change_type": p.get("change_type", ""),
                        "description": p.get("description", ""),
                        "new_value": p.get("new_value", {}),
                    }, on_conflict="org_id,source_agent_id,change_type,description").execute()
                    pushed += 1
                except Exception as exc:
                    logger.debug("push_setup_patterns row failed: %s", exc)
                    failed += 1
        except Exception as exc:
            logger.debug("push_setup_patterns failed: %s", exc)
            return {"pushed": pushed, "failed": failed + len(patterns) - pushed}

        return {"pushed": pushed, "failed": failed}

    def pull_setup_patterns(
        self, change_type: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Pull org setup patterns from Supabase.

        Args:
            change_type: Optional filter (e.g., 'threshold', 'mcp_gap').
            limit: Max patterns to return.

        Returns:
            List of setup pattern dicts, or [] on failure.
        """
        try:
            client = self._get_client()
            self._set_org_context(client)
            q = (
                client.table("org_setup_patterns")
                .select("change_type, description, new_value, source_agent_id, adoption_count, success_rate")
                .order("adoption_count", desc=True)
                .limit(limit)
            )
            if change_type:
                q = q.eq("change_type", change_type)
            result = q.execute()
            return result.data or []
        except Exception as exc:
            logger.warning("pull_setup_patterns failed: %s", exc)
            return []
