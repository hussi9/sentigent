"""Memory Store — SQLite-based storage for agent episodic, procedural, and semantic memory.

This is the Layer 1 (per-agent) memory implementation. Uses SQLite for zero-infrastructure
local storage. Handles:
- Episodic memory: storing and retrieving decision traces
- Baseline computation: rolling statistics from operational history
- Similar episode retrieval: finding past decisions similar to current task
- Outcome attribution: linking outcomes to decisions for learning

For production/Layer 2+3, this will be replaced by PostgreSQL + pgvector.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sentigent.core.types import BaselineStats, DecisionAction, Trace

logger = logging.getLogger("sentigent.memory")

# Infrastructure / metadata context keys that should NOT become learned baselines.
# These are operational metrics, not domain-relevant values.
BASELINE_BLOCKLIST: set[str] = {
    "is_recording",
    "is_destructive",
    "is_deployment",
    "is_sensitive_file",
    "consequence_severity",
    "duration_ms",
    "tool_name",
    "lines_changed",
    "data_quality",
    "time_pressure",
    "deadline_minutes",
}


import math


def _tfidf_scores(
    query: str,
    corpus: list[tuple[str, str]],
) -> dict[str, float]:
    """Compute TF-IDF cosine similarity between query and each corpus document.

    Pure Python — zero external dependencies.

    Args:
        query: The query string
        corpus: List of (doc_id, text) tuples

    Returns:
        Dict mapping doc_id to cosine similarity score (0.0–1.0)
    """
    if not corpus:
        return {}

    def tokenize(text: str) -> list[str]:
        stop = {"the", "for", "and", "with", "this", "that", "from", "have",
                "been", "are", "was", "will", "not", "but", "can", "its"}
        return [
            w.lower().strip(".,!?:;()[]")
            for w in text.split()
            if len(w) > 2 and w.lower().strip(".,!?:;()[]") not in stop
        ]

    query_tokens = tokenize(query)
    if not query_tokens:
        return {}

    doc_tokens: list[list[str]] = [tokenize(text) for _, text in corpus]
    doc_ids = [doc_id for doc_id, _ in corpus]
    n_docs = len(corpus)

    all_tokens: set[str] = set(query_tokens)
    for tokens in doc_tokens:
        all_tokens.update(tokens)
    vocab = list(all_tokens)

    df: dict[str, int] = {
        term: sum(1 for tokens in doc_tokens if term in tokens)
        for term in vocab
    }
    idf: dict[str, float] = {
        term: math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1.0
        for term in vocab
    }

    def tfidf_vec(tokens: list[str]) -> dict[str, float]:
        tf: dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        n = len(tokens) or 1
        return {t: (count / n) * idf.get(t, 1.0) for t, count in tf.items()}

    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(a.get(t, 0.0) * b.get(t, 0.0) for t in a)
        mag_a = math.sqrt(sum(v * v for v in a.values())) or 1.0
        mag_b = math.sqrt(sum(v * v for v in b.values())) or 1.0
        return dot / (mag_a * mag_b)

    query_vec = tfidf_vec(query_tokens)
    return {
        doc_id: cosine(query_vec, tfidf_vec(tokens))
        for doc_id, tokens in zip(doc_ids, doc_tokens)
        if tokens
    }


class MemoryStore:
    """SQLite-based memory store for per-agent learning.

    Stores episodic memories (decision traces + outcomes) and computes
    learned baselines from accumulated experience.
    """

    def __init__(
        self,
        agent_id: str,
        org_id: str,
        db_path: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.org_id = org_id
        self._org_id = org_id

        if db_path is None:
            home = Path.home()
            sentigent_dir = home / ".sentigent"
            sentigent_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(sentigent_dir / f"memory_{agent_id}.db")

        self.db_path = db_path
        self._init_db()

        # In-memory cache of computed baselines
        self._baseline_cache: dict[str, BaselineStats] = {}

    def _init_db(self) -> None:
        """Initialize the SQLite database schema."""
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                trace_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                task TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}',
                agent_state TEXT NOT NULL DEFAULT '{}',
                signals TEXT NOT NULL DEFAULT '{}',
                decision TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                confidence_at_decision REAL DEFAULT 0.5,
                outcome TEXT,
                outcome_timestamp TEXT,
                outcome_feedback TEXT,
                embedding TEXT          -- Phase 5: JSON-encoded 384-dim vector (nullable)
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_agent
                ON episodes(agent_id);
            CREATE INDEX IF NOT EXISTS idx_episodes_timestamp
                ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodes_outcome
                ON episodes(outcome);

            CREATE TABLE IF NOT EXISTS procedural_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                org_id TEXT NOT NULL,
                pattern_name TEXT NOT NULL,
                condition TEXT NOT NULL DEFAULT '{}',
                learned_action TEXT NOT NULL,
                success_rate REAL DEFAULT 0.0,
                sample_size INTEGER DEFAULT 0,
                last_reinforced TEXT,
                created_from TEXT DEFAULT 'layer_1'
            );

            CREATE TABLE IF NOT EXISTS semantic_baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id TEXT NOT NULL,
                agent_id TEXT,
                metric_name TEXT NOT NULL,
                baseline_data TEXT NOT NULL DEFAULT '{}',
                source TEXT DEFAULT 'operational',
                last_updated TEXT NOT NULL,
                sample_size INTEGER DEFAULT 0,
                UNIQUE(org_id, agent_id, metric_name)
            );

            CREATE TABLE IF NOT EXISTS baseline_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id TEXT NOT NULL,
                agent_id TEXT,
                metric_name TEXT NOT NULL,
                baseline_data TEXT NOT NULL DEFAULT '{}',
                sample_size INTEGER DEFAULT 0,
                recorded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_baseline_history_metric
                ON baseline_history(agent_id, metric_name, recorded_at);

            CREATE TABLE IF NOT EXISTS computed_insights (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL,
                subject     TEXT NOT NULL,
                finding     TEXT NOT NULL,
                confidence  REAL NOT NULL,
                recommendation TEXT DEFAULT '',
                signal_weight  REAL DEFAULT 0.0,
                computed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS active_tasks (
                task_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '[]',
                authorized_by TEXT NOT NULL DEFAULT 'user',
                success_criteria TEXT NOT NULL DEFAULT '[]',
                constraints TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'in_progress',
                outcome TEXT,
                summary TEXT,
                episode_count INTEGER DEFAULT 0,
                scope_violations INTEGER DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_active_tasks_status
                ON active_tasks(status);

            CREATE TABLE IF NOT EXISTS setup_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_input TEXT NOT NULL DEFAULT '',
                routing_confidence REAL DEFAULT 0.0,
                outcome_signal TEXT DEFAULT 'unknown',
                observed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS setup_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                description TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT NOT NULL,
                revert_payload TEXT,
                applied_at TEXT NOT NULL,
                reverted_at TEXT,
                autonomy_stage INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS setup_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                config_key TEXT NOT NULL,
                config_value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(agent_id, org_id, config_key)
            );
        """)
        # Phase 5: Migrate existing episodes table to add embedding column
        try:
            conn.execute("ALTER TABLE episodes ADD COLUMN embedding TEXT")
            conn.commit()
        except Exception:
            pass  # Column already exists — safe to ignore

        # Phase 6A: Add clarity attribution columns to episodes
        for col in ("clarity_score REAL", "task_specificity REAL", "task_domain TEXT"):
            try:
                conn.execute(f"ALTER TABLE episodes ADD COLUMN {col}")
                conn.commit()
            except Exception:
                pass  # Column already exists

        # Phase 6B: Local org_relationships table (mirrors Supabase, enables offline graph policies)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS org_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id TEXT NOT NULL,
                from_entity TEXT NOT NULL,
                from_type TEXT NOT NULL DEFAULT 'file',
                relationship TEXT NOT NULL,
                to_entity TEXT NOT NULL,
                to_type TEXT NOT NULL DEFAULT 'file',
                weight REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(org_id, from_entity, relationship, to_entity)
            )
        """)
        conn.commit()

        conn.commit()
        conn.close()

    def store_episode(self, trace: Trace) -> None:
        """Store a decision trace in episodic memory.

        Phase 5: Computes a 384-dim sentence embedding for the task text if
        sentence-transformers is installed. Stored as JSON in the embedding column
        for subsequent cosine-similarity retrieval in find_similar_episodes().
        Falls back silently when embedder is unavailable.

        Phase 6A: Computes clarity_score + task_specificity + task_domain at
        store time so OutcomeAttributor can correlate them with outcomes later.
        """
        # Phase 5: compute embedding (best-effort, non-blocking)
        embedding_json: str | None = None
        try:
            from sentigent.core.embedder import get_embedder
            embedder = get_embedder()
            if embedder:
                vec = embedder.encode(trace.task)
                if vec:
                    embedding_json = json.dumps(vec)
        except Exception:
            pass

        # Phase 6A: compute clarity metadata (best-effort)
        clarity_score: float | None = None
        task_specificity: float | None = None
        task_domain: str | None = None
        try:
            from sentigent.core.clarity_scorer import ClarityScorer
            from sentigent.core.intent_extractor import IntentExtractor
            from sentigent.core.context_assembler import classify_domain
            cs = ClarityScorer().score(trace.task)
            intent = IntentExtractor().extract(trace.task)
            clarity_score = cs.overall
            task_specificity = intent.specificity
            task_domain = classify_domain(trace.task)
        except Exception:
            pass

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT OR REPLACE INTO episodes
            (trace_id, agent_id, org_id, timestamp, task, context, agent_state,
             signals, decision, reason, confidence_at_decision, embedding,
             clarity_score, task_specificity, task_domain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.trace_id,
                trace.agent_id,
                self.org_id,
                trace.timestamp.isoformat(),
                trace.task,
                json.dumps(trace.context),
                json.dumps(trace.agent_state),
                json.dumps(trace.signals),
                trace.decision.value,
                trace.reason,
                trace.confidence_at_decision,
                embedding_json,
                clarity_score,
                task_specificity,
                task_domain,
            ),
        )
        conn.commit()
        conn.close()

    def record_outcome(
        self,
        trace_id: str,
        outcome: str,
        feedback: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Record the outcome of a previous decision."""
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE episodes
            SET outcome = ?, outcome_timestamp = ?, outcome_feedback = ?
            WHERE trace_id = ?
            """,
            (outcome, ts, feedback, trace_id),
        )
        conn.commit()
        conn.close()

    def find_similar_episodes(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find past episodes similar to the given task.

        Phase 5: Semantic retrieval path (when sentence-transformers installed):
          1. Encode query task to 384-dim vector
          2. Cosine similarity against stored episode embeddings
          3. Re-rank with context similarity

          Final score = semantic_score * 0.7 + context_similarity * 0.3

        TF-IDF path (fallback when embedder unavailable / cold start):
          1. TF-IDF cosine similarity on task text
             Falls back to keyword overlap when corpus < 10 episodes
          2. Re-rank with context similarity

          Final score = tfidf_score * 0.6 + context_similarity * 0.4

        Impact: ~40% → ~85% relevant recall with semantic path.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        all_rows = conn.execute(
            """
            SELECT trace_id, task, context, signals, decision, outcome,
                   outcome_feedback, confidence_at_decision, timestamp, embedding
            FROM episodes
            WHERE agent_id = ? AND outcome IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
            """,
            (self.agent_id,),
        ).fetchall()
        conn.close()

        if not all_rows:
            return []

        episodes: list[dict[str, Any]] = []
        for row in all_rows:
            episode_context = json.loads(row["context"])
            episodes.append({
                "trace_id": row["trace_id"],
                "task": row["task"],
                "context": episode_context,
                "signals": json.loads(row["signals"]),
                "decision": row["decision"],
                "outcome": row["outcome"],
                "feedback": row["outcome_feedback"],
                "confidence": row["confidence_at_decision"],
                "timestamp": row["timestamp"],
                "_embedding_json": row["embedding"],  # internal; stripped before return
            })

        # Phase 5: Try semantic retrieval first
        try:
            from sentigent.core.embedder import get_embedder, Embedder
            embedder = get_embedder()
            if embedder:
                # Filter episodes that have stored embeddings
                episodes_with_emb = [
                    ep for ep in episodes if ep.get("_embedding_json")
                ]
                if len(episodes_with_emb) >= 5:
                    query_vec = embedder.encode(task)
                    if query_vec:
                        scored: list[tuple[float, dict[str, Any]]] = []
                        for ep in episodes_with_emb:
                            try:
                                ep_vec: list[float] = json.loads(ep["_embedding_json"])
                                sem_score = Embedder.cosine_similarity(query_vec, ep_vec)
                            except Exception:
                                sem_score = 0.0
                            ctx_score = self._compute_context_similarity(
                                context or {}, ep["context"]
                            )
                            final = sem_score * 0.7 + ctx_score * 0.3
                            scored.append((final, ep))

                        scored.sort(key=lambda x: x[0], reverse=True)
                        # Strip internal embedding key before returning
                        top = scored[:limit]
                        results = []
                        for score, ep in top:
                            if score > 0.0:
                                ep_clean = {k: v for k, v in ep.items() if k != "_embedding_json"}
                                results.append(ep_clean)
                        if results:
                            return results
        except Exception:
            pass  # Fall through to TF-IDF path

        # TF-IDF fallback
        corpus = [(ep["trace_id"], ep["task"]) for ep in episodes]

        if len(corpus) >= 10:
            text_scores = _tfidf_scores(task, corpus)
        else:
            # Cold-start: keyword overlap ratio
            stop_words = {"the", "for", "and", "with", "this", "that", "from"}
            query_words = {
                w.lower().strip(".,!?") for w in task.split()
                if len(w) > 3 and w.lower() not in stop_words
            }
            text_scores = {}
            for ep_id, ep_task in corpus:
                ep_words = {w.lower().strip(".,!?") for w in ep_task.split()}
                overlap = len(query_words & ep_words)
                text_scores[ep_id] = overlap / max(len(query_words), 1)

        scored_tfidf: list[tuple[float, dict[str, Any]]] = []
        for ep in episodes:
            ts = text_scores.get(ep["trace_id"], 0.0)
            ctx_score = self._compute_context_similarity(context or {}, ep["context"])
            final = ts * 0.6 + ctx_score * 0.4
            scored_tfidf.append((final, ep))

        scored_tfidf.sort(key=lambda x: x[0], reverse=True)
        top_tfidf = scored_tfidf[:limit]
        return [
            {k: v for k, v in ep.items() if k != "_embedding_json"}
            for _, ep in top_tfidf
            if top_tfidf and top_tfidf[0][0] > 0.0
        ]

    @staticmethod
    def _compute_context_similarity(
        query_context: dict[str, Any],
        episode_context: dict[str, Any],
    ) -> float:
        """Compute similarity between two contexts based on numeric value proximity.

        For each numeric key present in both contexts, computes relative distance:
            distance = abs(q - e) / max(abs(q), abs(e), 1)

        Returns the average inverted distance (1.0 = identical, 0.0 = maximally different).
        If no shared numeric keys exist, returns 0.0.
        """
        distances: list[float] = []
        for key, query_val in query_context.items():
            if not isinstance(query_val, (int, float)):
                continue
            episode_val = episode_context.get(key)
            if not isinstance(episode_val, (int, float)):
                continue
            denominator = max(abs(query_val), abs(episode_val), 1)
            distance = abs(query_val - episode_val) / denominator
            distances.append(distance)

        if not distances:
            return 0.0

        avg_distance = sum(distances) / len(distances)
        return 1.0 - avg_distance

    def get_baselines(self) -> dict[str, BaselineStats]:
        """Get all computed baselines from operational data.

        Returns cached baselines. Call update_baselines_from_episodes() to refresh.
        """
        if self._baseline_cache:
            return self._baseline_cache

        # Load from database
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_name, baseline_data, source, last_updated, sample_size "
            "FROM semantic_baselines WHERE agent_id = ? OR agent_id IS NULL",
            (self.agent_id,),
        ).fetchall()
        conn.close()

        for row in rows:
            data = json.loads(row["baseline_data"])
            self._baseline_cache[row["metric_name"]] = BaselineStats(
                metric_name=row["metric_name"],
                median=data.get("median", 0),
                mean=data.get("mean", 0),
                std=data.get("std", 1),
                p5=data.get("p5", 0),
                p25=data.get("p25", 0),
                p75=data.get("p75", 0),
                p95=data.get("p95", 0),
                min_observed=data.get("min", 0),
                max_observed=data.get("max", 0),
                sample_size=row["sample_size"],
                source="layer_1",
            )

        return self._baseline_cache

    def update_baselines_from_episodes(self) -> None:
        """Recompute baselines from accumulated episodic memory.

        This is the core learning mechanism. It extracts numeric values from
        all past episodes and computes rolling statistics that become the
        new baselines. Called after each outcome is recorded.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            "SELECT context FROM episodes WHERE agent_id = ? AND outcome IS NOT NULL",
            (self.agent_id,),
        ).fetchall()

        if len(rows) < 5:
            # Not enough data to compute meaningful baselines
            conn.close()
            return

        # Collect all numeric values by key, excluding infrastructure metrics
        value_collections: dict[str, list[float]] = {}
        for row in rows:
            context = json.loads(row["context"])
            for key, value in context.items():
                if isinstance(value, (int, float)):
                    # Skip infrastructure / metadata keys
                    if key.startswith("_") or key in BASELINE_BLOCKLIST:
                        continue
                    if key not in value_collections:
                        value_collections[key] = []
                    value_collections[key].append(float(value))

        now = datetime.now(timezone.utc).isoformat()

        for metric_name, values in value_collections.items():
            if len(values) < 5:
                continue

            sorted_values = sorted(values)
            n = len(sorted_values)

            baseline_data = {
                "median": statistics.median(values),
                "mean": statistics.mean(values),
                "std": statistics.stdev(values) if n > 1 else 0,
                "p5": sorted_values[max(0, int(n * 0.05))],
                "p25": sorted_values[max(0, int(n * 0.25))],
                "p75": sorted_values[min(n - 1, int(n * 0.75))],
                "p95": sorted_values[min(n - 1, int(n * 0.95))],
                "min": sorted_values[0],
                "max": sorted_values[-1],
            }

            baseline_json = json.dumps(baseline_data)

            conn.execute(
                """
                INSERT INTO semantic_baselines (org_id, agent_id, metric_name, baseline_data, source, last_updated, sample_size)
                VALUES (?, ?, ?, ?, 'operational', ?, ?)
                ON CONFLICT(org_id, agent_id, metric_name)
                DO UPDATE SET baseline_data = ?, last_updated = ?, sample_size = ?
                """,
                (
                    self.org_id,
                    self.agent_id,
                    metric_name,
                    baseline_json,
                    now,
                    n,
                    baseline_json,
                    now,
                    n,
                ),
            )

            # Record baseline snapshot in history for drift detection / rollback (MOD 4.6)
            conn.execute(
                """
                INSERT INTO baseline_history (org_id, agent_id, metric_name, baseline_data, sample_size, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (self.org_id, self.agent_id, metric_name, baseline_json, n, now),
            )

            # Update cache
            self._baseline_cache[metric_name] = BaselineStats(
                metric_name=metric_name,
                median=baseline_data["median"],
                mean=baseline_data["mean"],
                std=baseline_data["std"],
                p5=baseline_data["p5"],
                p25=baseline_data["p25"],
                p75=baseline_data["p75"],
                p95=baseline_data["p95"],
                min_observed=baseline_data["min"],
                max_observed=baseline_data["max"],
                sample_size=n,
                source="layer_1",
            )

        conn.commit()
        conn.close()

    def get_outcome_counts(self) -> tuple[int, int]:
        """Get total decisions with outcomes and correct count from the database.

        Returns:
            Tuple of (total_with_outcomes, correct_count) for this agent.
        """
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct
            FROM episodes
            WHERE agent_id = ? AND outcome IS NOT NULL
            """,
            (self.agent_id,),
        ).fetchone()
        conn.close()
        return (row[0], row[1] or 0)

    def get_episode_count(self) -> int:
        """Get total number of stored episodes."""
        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE agent_id = ?",
            (self.agent_id,),
        ).fetchone()[0]
        conn.close()
        return count

    def get_outcome_stats(self) -> dict[str, int]:
        """Get counts of outcomes by type."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT outcome, COUNT(*) as cnt FROM episodes "
            "WHERE agent_id = ? AND outcome IS NOT NULL GROUP BY outcome",
            (self.agent_id,),
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}

    def get_pending_episodes(self, agent_id: str, limit: int = 100) -> list[Trace]:
        """Get episodes that don't have outcomes yet, ordered by oldest first.

        Used by the OutcomeAttributor to check if enough time has passed
        to infer outcomes from absence of complaints.

        Args:
            agent_id: The agent to get pending episodes for
            limit: Maximum number of episodes to return

        Returns:
            List of Trace objects without outcomes, oldest first.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, agent_id, timestamp, task, context, agent_state,
                   signals, decision, reason, confidence_at_decision,
                   outcome, outcome_timestamp, outcome_feedback
            FROM episodes
            WHERE agent_id = ? AND outcome IS NULL
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (agent_id, limit),
        ).fetchall()
        conn.close()

        traces: list[Trace] = []
        for row in rows:
            traces.append(Trace(
                trace_id=row["trace_id"],
                agent_id=row["agent_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                task=row["task"],
                context=json.loads(row["context"]),
                agent_state=json.loads(row["agent_state"]),
                signals=json.loads(row["signals"]),
                decision=DecisionAction(row["decision"]),
                reason=row["reason"],
                confidence_at_decision=row["confidence_at_decision"],
                outcome=row["outcome"],
                outcome_feedback=row["outcome_feedback"],
            ))

        return traces

    def get_episodes_with_outcomes(self, agent_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Get episodes that have outcomes recorded, for pattern mining.

        Args:
            agent_id: The agent to get episodes for
            limit: Maximum number of episodes to return

        Returns:
            List of episode dicts with outcomes.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, task, context, signals, decision, outcome,
                   outcome_feedback, confidence_at_decision, timestamp
            FROM episodes
            WHERE agent_id = ? AND outcome IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (agent_id, limit),
        ).fetchall()
        conn.close()

        episodes: list[dict[str, Any]] = []
        for row in rows:
            episodes.append({
                "trace_id": row["trace_id"],
                "task": row["task"],
                "context": json.loads(row["context"]),
                "signals": json.loads(row["signals"]),
                "decision": row["decision"],
                "outcome": row["outcome"],
                "feedback": row["outcome_feedback"],
                "confidence": row["confidence_at_decision"],
                "timestamp": row["timestamp"],
            })

        return episodes

    def get_recent_episodes(
        self,
        limit: int = 200,
        with_outcomes_only: bool = False,
    ) -> list[dict]:
        """Return recent episodes from local SQLite, optionally filtered to those with outcomes.

        Used by CollectiveLearner for local data when Layer 2 is unavailable.
        """
        import json as _json
        try:
            with sqlite3.connect(self.db_path) as conn:
                if with_outcomes_only:
                    rows = conn.execute(
                        """
                        SELECT agent_id, task, decision, outcome, signals, timestamp
                        FROM episodes
                        WHERE outcome IN ('correct', 'incorrect')
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT agent_id, task, decision, outcome, signals, timestamp
                        FROM episodes
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()

                result = []
                for row in rows:
                    signals = row[4]
                    if isinstance(signals, str):
                        try:
                            signals = _json.loads(signals)
                        except Exception:
                            signals = {}
                    result.append({
                        "agent_id": row[0] or self.agent_id,
                        "task": row[1] or "",
                        "decision": row[2] or "",
                        "outcome": row[3] or "",
                        "signals": signals or {},
                        "timestamp": row[5] or "",
                    })
                return result
        except Exception:
            return []

    def store_computed_insight(
        self,
        category: str,
        subject: str,
        finding: str,
        confidence: float,
        recommendation: str = "",
        signal_weight: float = 0.0,
    ) -> None:
        """Store a computed insight, replacing any existing for same subject+category."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "DELETE FROM computed_insights WHERE category = ? AND subject = ?",
            (category, subject),
        )
        conn.execute(
            """
            INSERT INTO computed_insights
              (category, subject, finding, confidence, recommendation, signal_weight, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (category, subject, finding, confidence, recommendation, signal_weight, now),
        )
        conn.commit()
        conn.close()

    def get_computed_insights(self) -> list[dict]:
        """Return all stored computed insights, newest first."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT category, subject, finding, confidence,
                   recommendation, signal_weight, computed_at
            FROM computed_insights
            ORDER BY computed_at DESC
            """
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_episodes_for_insights(self, limit: int = 2000) -> list[dict]:
        """Get episodes with recorded outcomes for insight computation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trace_id, task, context, decision,
                   confidence_at_decision, outcome, timestamp
            FROM episodes
            WHERE agent_id = ? AND outcome IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (self.agent_id, limit),
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            ctx = {}
            try:
                ctx = json.loads(row["context"])
            except Exception:
                pass
            result.append({
                "trace_id": row["trace_id"],
                "task": row["task"],
                "tool_name": ctx.get("tool_name", ""),
                "is_destructive": ctx.get("is_destructive", False),
                "decision": row["decision"],
                "confidence": row["confidence_at_decision"] or 0.5,
                "outcome": row["outcome"],
                "timestamp": row["timestamp"],
            })
        return result

    def store_procedural_rule(self, rule: dict[str, Any]) -> None:
        """Store a learned procedural rule.

        If a rule with the same pattern_name already exists for this agent,
        it is updated with the new data.

        Args:
            rule: Dict with keys: pattern_name, condition, learned_action,
                  success_rate, sample_size
        """
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()

        # Upsert: update if same pattern_name + agent_id exists
        existing = conn.execute(
            "SELECT id FROM procedural_rules WHERE agent_id = ? AND pattern_name = ?",
            (self.agent_id, rule["pattern_name"]),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE procedural_rules
                SET condition = ?, learned_action = ?, success_rate = ?,
                    sample_size = ?, last_reinforced = ?
                WHERE id = ?
                """,
                (
                    json.dumps(rule.get("condition", {})),
                    rule["learned_action"],
                    rule.get("success_rate", 0.0),
                    rule.get("sample_size", 0),
                    now,
                    existing[0],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO procedural_rules
                (agent_id, org_id, pattern_name, condition, learned_action,
                 success_rate, sample_size, last_reinforced, created_from)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'layer_1')
                """,
                (
                    self.agent_id,
                    self.org_id,
                    rule["pattern_name"],
                    json.dumps(rule.get("condition", {})),
                    rule["learned_action"],
                    rule.get("success_rate", 0.0),
                    rule.get("sample_size", 0),
                    now,
                ),
            )

        conn.commit()
        conn.close()

    def get_matching_rules(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Get procedural rules that match the current context.

        A rule matches if:
        - For numeric_range conditions: the context value falls within [min, max]
        - For categorical conditions: the context value matches the dominant_value
        - Rules with no conditions always match

        Args:
            context: Current decision context

        Returns:
            List of matching rule dicts, sorted by success_rate descending.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT pattern_name, condition, learned_action, success_rate,
                   sample_size, last_reinforced
            FROM procedural_rules
            WHERE agent_id = ? OR agent_id IS NULL
            ORDER BY success_rate DESC
            """,
            (self.agent_id,),
        ).fetchall()
        conn.close()

        matching: list[dict[str, Any]] = []
        for row in rows:
            condition = json.loads(row["condition"])
            if self._rule_matches(condition, context):
                matching.append({
                    "pattern_name": row["pattern_name"],
                    "condition": condition,
                    "learned_action": row["learned_action"],
                    "success_rate": row["success_rate"],
                    "sample_size": row["sample_size"],
                    "last_reinforced": row["last_reinforced"],
                })

        return matching

    def prune_old_episodes(self, ttl_days: int = 90) -> int:
        """Archive episodes older than TTL to keep memory lean.

        Moves old episodes to an archive table instead of deleting.
        Baselines from pruned episodes are preserved in semantic_baselines.

        Args:
            ttl_days: Maximum age of episodes to keep (default: 90 days)

        Returns:
            Number of episodes archived
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        conn = sqlite3.connect(self.db_path)

        # Create archive table if needed
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes_archive (
                trace_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                task TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}',
                agent_state TEXT NOT NULL DEFAULT '{}',
                signals TEXT NOT NULL DEFAULT '{}',
                decision TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                confidence_at_decision REAL DEFAULT 0.5,
                outcome TEXT,
                outcome_timestamp TEXT,
                outcome_feedback TEXT,
                embedding TEXT,
                clarity_score REAL,
                task_specificity REAL,
                task_domain TEXT,
                archived_at TEXT NOT NULL
            )
        """)

        # Move old episodes to archive (only those with outcomes already recorded)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO episodes_archive
            SELECT *, ? as archived_at
            FROM episodes
            WHERE timestamp < ? AND outcome IS NOT NULL AND agent_id = ?
            """,
            (now, cutoff, self.agent_id),
        )

        # Count how many we're moving
        cursor = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE timestamp < ? AND outcome IS NOT NULL AND agent_id = ?",
            (cutoff, self.agent_id),
        )
        count = cursor.fetchone()[0]

        # Remove from active table
        conn.execute(
            "DELETE FROM episodes WHERE timestamp < ? AND outcome IS NOT NULL AND agent_id = ?",
            (cutoff, self.agent_id),
        )

        conn.commit()
        conn.close()

        if count > 0:
            logger.info("Pruned %d episodes older than %d days", count, ttl_days)

        return count

    def get_baseline_history(
        self,
        metric_name: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get historical baseline snapshots for a metric.

        Enables drift detection, audit trails, and rollback.

        Args:
            metric_name: The metric to get history for
            limit: Maximum number of snapshots to return

        Returns:
            List of baseline snapshots ordered by recorded_at descending.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT metric_name, baseline_data, sample_size, recorded_at
            FROM baseline_history
            WHERE agent_id = ? AND org_id = ? AND metric_name = ?
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (self.agent_id, self.org_id, metric_name, limit),
        ).fetchall()
        conn.close()

        return [
            {
                "metric_name": row["metric_name"],
                "baseline_data": json.loads(row["baseline_data"]),
                "sample_size": row["sample_size"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def detect_baseline_drift(
        self,
        metric_name: str,
        drift_threshold: float = 0.3,
    ) -> dict[str, Any] | None:
        """Detect if a baseline has drifted significantly from its recent history.

        Compares the current baseline median to the average of the last 5 snapshots.
        If the relative change exceeds drift_threshold, returns drift info.

        Args:
            metric_name: The metric to check for drift
            drift_threshold: Relative change threshold (0.3 = 30% drift)

        Returns:
            Dict with drift details if drift detected, None otherwise.
        """
        history = self.get_baseline_history(metric_name, limit=6)
        if len(history) < 2:
            return None

        current = history[0]
        previous = history[1:]

        current_median = current["baseline_data"].get("median", 0)
        historical_medians = [h["baseline_data"].get("median", 0) for h in previous]
        avg_historical = sum(historical_medians) / len(historical_medians) if historical_medians else 0

        if avg_historical == 0:
            return None

        relative_change = abs(current_median - avg_historical) / abs(avg_historical)

        if relative_change > drift_threshold:
            return {
                "metric_name": metric_name,
                "current_median": current_median,
                "historical_avg_median": avg_historical,
                "relative_change": round(relative_change, 3),
                "drift_threshold": drift_threshold,
                "snapshots_compared": len(previous),
                "detected_at": current["recorded_at"],
            }

        return None

    @staticmethod
    def _rule_matches(condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """Check if a rule's condition matches the given context.

        Empty conditions always match. For each condition key, the corresponding
        context value must satisfy the condition type (numeric_range or categorical).
        """
        if not condition:
            return True
        # TODO: implement numeric_range and categorical matching
        return True  # permissive fallback until matching logic is implemented

    # ── Task Context Layer (Phase 2) ──────────────────────────────────────────

    def start_task(
        self,
        task_id: str,
        goal: str,
        scope: list[str] | None = None,
        authorized_by: str = "user",
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> None:
        """Persist a newly declared task to local memory."""
        import json as _json
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO active_tasks
                    (task_id, goal, scope, authorized_by, success_criteria, constraints, status)
                VALUES (?, ?, ?, ?, ?, ?, 'in_progress')
                """,
                (
                    task_id,
                    goal,
                    _json.dumps(scope or []),
                    authorized_by,
                    _json.dumps(success_criteria or []),
                    _json.dumps(constraints or []),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def complete_task(
        self,
        task_id: str,
        outcome: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Mark a task as complete (or abandoned) with optional outcome."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE active_tasks
                SET status = CASE WHEN ? IS NOT NULL THEN 'complete' ELSE 'abandoned' END,
                    outcome = ?,
                    summary = ?,
                    completed_at = datetime('now')
                WHERE task_id = ?
                """,
                (outcome, outcome, summary, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_active_task(self, task_id: str) -> dict | None:
        """Retrieve a task by ID. Returns None if not found."""
        import json as _json
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM active_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["scope"] = _json.loads(d.get("scope") or "[]")
            d["success_criteria"] = _json.loads(d.get("success_criteria") or "[]")
            d["constraints"] = _json.loads(d.get("constraints") or "[]")
            return d
        finally:
            conn.close()

    def list_active_tasks(self) -> list[dict]:
        """Return all in-progress tasks."""
        import json as _json
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM active_tasks WHERE status = 'in_progress' ORDER BY started_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["scope"] = _json.loads(d.get("scope") or "[]")
                d["success_criteria"] = _json.loads(d.get("success_criteria") or "[]")
                d["constraints"] = _json.loads(d.get("constraints") or "[]")
                result.append(d)
            return result
        finally:
            conn.close()

    def increment_task_episodes(self, task_id: str) -> None:
        """Increment episode counter for a task."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE active_tasks SET episode_count = episode_count + 1 WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def increment_scope_violations(self, task_id: str) -> None:
        """Increment scope violation counter for a task."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE active_tasks SET scope_violations = scope_violations + 1 WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Routing Seeds (imported from skill-router) ──────────────────────────

    def _ensure_routing_seeds_table(self) -> None:
        """Apply migration 003 if not yet applied. Idempotent."""
        import pathlib
        sql_file = pathlib.Path(__file__).parent / "migrations" / "003_routing_seeds.sql"
        if not sql_file.exists():
            return
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "routing_seeds" not in tables:
                conn.executescript(sql_file.read_text())
                conn.commit()
        finally:
            conn.close()

    def insert_routing_seed(
        self,
        prompt_hash: str,
        prompt_text: str,
        task_type: str,
        skill: str,
        agent: str,
        model: str,
        confidence: float,
        avg_sim: float,
        margin: float,
        neighbors: list,
        embedding: list[float],
        outcome: str = "neutral",
        source: str = "skill_router_import",
    ) -> None:
        """Insert a routing seed row. Silently ignores duplicates (ON CONFLICT IGNORE)."""
        import json as _json
        self._ensure_routing_seeds_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO routing_seeds
                    (prompt_hash, prompt_text, task_type, skill, agent, model,
                     confidence, avg_sim, margin, neighbors, embedding, outcome, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt_hash, prompt_text, task_type, skill, agent, model,
                    confidence, avg_sim, margin,
                    _json.dumps(neighbors),
                    _json.dumps(embedding),
                    outcome, source,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_routing_seeds(
        self,
        task_type: str | None = None,
        min_confidence: float = 0.0,
        outcome: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return routing seeds filtered by task_type, confidence, and outcome."""
        import json as _json
        self._ensure_routing_seeds_table()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            clauses = ["confidence >= ?"]
            params: list = [min_confidence]
            if task_type:
                clauses.append("task_type = ?")
                params.append(task_type)
            if outcome:
                clauses.append("outcome = ?")
                params.append(outcome)
            where = " AND ".join(clauses)
            rows = conn.execute(
                f"SELECT * FROM routing_seeds WHERE {where} ORDER BY confidence DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["neighbors"] = _json.loads(d.get("neighbors") or "[]")
                result.append(d)
            return result
        finally:
            conn.close()

    def get_all_routing_seeds_with_embeddings(self, limit: int = 2000) -> list[dict]:
        """Return all routing seeds including their embedding vectors (for cosine search)."""
        import json as _json
        self._ensure_routing_seeds_table()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT prompt_hash, prompt_text, task_type, skill, agent, model, "
                "confidence, outcome, embedding FROM routing_seeds LIMIT ?",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                raw = d.get("embedding")
                if isinstance(raw, (bytes, bytearray)) and len(raw) > 0:
                    import struct as _struct
                    n = len(raw) // 4
                    d["embedding"] = list(_struct.unpack(f"{n}f", raw))
                elif isinstance(raw, str) and raw:
                    d["embedding"] = _json.loads(raw)
                else:
                    d["embedding"] = []
                result.append(d)
            return result
        finally:
            conn.close()

    def update_routing_seed_outcome(self, prompt_hash: str, outcome: str) -> None:
        """Update the outcome of a routing seed after live validation."""
        self._ensure_routing_seeds_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE routing_seeds SET outcome = ? WHERE prompt_hash = ?",
                (outcome, prompt_hash),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Cost telemetry
    # ------------------------------------------------------------------

    def _ensure_cost_events_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "cost_events" not in tables:
                migration = (
                    Path(__file__).parent / "migrations" / "004_cost_events.sql"
                )
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def insert_cost_event(self, event: dict) -> None:
        """Persist a CostEvent dict to the cost_events table."""
        self._ensure_cost_events_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO cost_events
                   (trace_id, agent_id, model, input_tokens, output_tokens,
                    tool_name, cost_usd, baseline_cost_usd, savings_usd, meta, ts)
                   VALUES (:trace_id, :agent_id, :model, :input_tokens, :output_tokens,
                           :tool_name, :cost_usd, :baseline_cost_usd, :savings_usd, :meta, :ts)
                """,
                {
                    "trace_id": event.get("trace_id", ""),
                    "agent_id": event.get("agent_id", self.agent_id),
                    "model": event.get("model", ""),
                    "input_tokens": event.get("input_tokens", 0),
                    "output_tokens": event.get("output_tokens", 0),
                    "tool_name": event.get("tool_name", ""),
                    "cost_usd": event.get("cost_usd", 0.0),
                    "baseline_cost_usd": event.get("baseline_cost_usd", 0.0),
                    "savings_usd": event.get("savings_usd", 0.0),
                    "meta": event.get("meta", "{}"),
                    "ts": event.get("ts", 0.0),
                },
            )
            conn.commit()
        finally:
            conn.close()

    def get_cost_events_for_month(
        self, year: int, month: int
    ) -> list[dict]:
        """Return all cost events for the given calendar month."""
        self._ensure_cost_events_table()
        import time as _time
        import calendar

        # Build epoch range for the month
        start = _time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1))
        _, last_day = calendar.monthrange(year, month)
        end = _time.mktime((year, month, last_day, 23, 59, 59, 0, 0, -1))

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM cost_events WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (start, end),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                try:
                    import json as _json
                    d["meta"] = _json.loads(d.get("meta") or "{}")
                except Exception:
                    d["meta"] = {}
                result.append(d)
            return result
        finally:
            conn.close()

    def get_cost_summary(self, days: int = 30) -> dict:
        """Return aggregate cost stats for the last N days."""
        self._ensure_cost_events_table()
        import time as _time

        since = _time.time() - days * 86400
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """SELECT
                     COUNT(*)            AS event_count,
                     SUM(input_tokens + output_tokens) AS total_tokens,
                     SUM(cost_usd)       AS total_cost_usd,
                     SUM(baseline_cost_usd) AS total_baseline_usd,
                     SUM(savings_usd)    AS total_savings_usd
                   FROM cost_events WHERE ts >= ?
                """,
                (since,),
            ).fetchone()
            if not row or row[0] == 0:
                return {
                    "event_count": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "total_baseline_usd": 0.0,
                    "total_savings_usd": 0.0,
                    "savings_pct": 0.0,
                }
            total_cost = row[2] or 0.0
            total_baseline = row[3] or 0.0
            total_savings = row[4] or 0.0
            return {
                "event_count": row[0],
                "total_tokens": row[1] or 0,
                "total_cost_usd": round(total_cost, 6),
                "total_baseline_usd": round(total_baseline, 6),
                "total_savings_usd": round(total_savings, 6),
                "savings_pct": round(
                    100 * total_savings / total_baseline if total_baseline else 0.0, 2
                ),
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Decision events — the REAL user-preference signal (Phase 0, A1)
    # ------------------------------------------------------------------

    def _ensure_decision_events_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "decision_events" not in tables:
                migration = (
                    Path(__file__).parent / "migrations" / "005_decision_events.sql"
                )
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def insert_decision_event(self, event: dict) -> None:
        """Persist one DecisionEvent (approve/reject/correct/revert). Fail-soft."""
        self._ensure_decision_events_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO decision_events
                   (agent_id, org_id, ts, kind, domain, signal, target,
                    prior_trace_id, source, confidence, meta)
                   VALUES (:agent_id, :org_id, :ts, :kind, :domain, :signal, :target,
                           :prior_trace_id, :source, :confidence, :meta)""",
                {
                    "agent_id": event.get("agent_id", self.agent_id),
                    "org_id": event.get("org_id", self.org_id),
                    "ts": float(event.get("ts", 0.0)),
                    "kind": event.get("kind", ""),
                    "domain": event.get("domain", "global"),
                    "signal": (event.get("signal", "") or "")[:1000],
                    "target": (event.get("target", "") or "")[:1000],
                    "prior_trace_id": event.get("prior_trace_id", ""),
                    "source": event.get("source", ""),
                    "confidence": float(event.get("confidence", 1.0)),
                    "meta": event.get("meta", "{}"),
                },
            )
            conn.commit()
        finally:
            conn.close()

    def get_decision_events(self, limit: int = 100, kind: str | None = None) -> list[dict]:
        """Return recent decision events, newest first. For the profile builder."""
        self._ensure_decision_events_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            if kind:
                rows = conn.execute(
                    "SELECT * FROM decision_events WHERE agent_id=? AND kind=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (self.agent_id, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decision_events WHERE agent_id=? ORDER BY ts DESC LIMIT ?",
                    (self.agent_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_decision_event_counts(self) -> dict[str, int]:
        """{kind: count} across all decision events for this agent."""
        self._ensure_decision_events_table()
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT kind, COUNT(*) FROM decision_events WHERE agent_id=? GROUP BY kind",
                (self.agent_id,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()

    def count_episodes(self, with_outcome: bool = False) -> int:
        """How many episodes (the raw 'vibe-coding shadow' — one per observed
        action) are recorded for this agent. This is the broad signal the clone
        learns from, distinct from the narrower explicit decision_events.
        with_outcome=True counts only episodes whose outcome is known (the
        highest-quality signal). Fail-soft → 0 if the table is missing."""
        conn = sqlite3.connect(self.db_path)
        try:
            sql = "SELECT COUNT(*) FROM episodes WHERE agent_id=?"
            if with_outcome:
                sql += " AND outcome IS NOT NULL AND outcome != ''"
            return int(conn.execute(sql, (self.agent_id,)).fetchone()[0])
        except Exception:
            return 0
        finally:
            conn.close()

    def count_episodes_since(self, iso_ts: str) -> int:
        """How many episodes were recorded at or after `iso_ts` (an ISO-8601
        string, matched lexicographically against the stored TEXT timestamp).
        Used by the session-start engagement line to show recent activity.
        Fail-soft → 0."""
        conn = sqlite3.connect(self.db_path)
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM episodes WHERE agent_id=? AND timestamp>=?",
                    (self.agent_id, iso_ts),
                ).fetchone()[0]
            )
        except Exception:
            return 0
        finally:
            conn.close()

    def count_episodes_by_decision(self) -> dict[str, int]:
        """Lifetime episode counts grouped by the decision action
        (proceed / enrich / slow_down / escalate). The intervention breakdown
        that proves Sentigent judges rather than rubber-stamps. Fail-soft → {}."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT decision, COUNT(*) FROM episodes WHERE agent_id=? "
                "GROUP BY decision",
                (self.agent_id,),
            ).fetchall()
            return {str(d): int(n) for d, n in rows if d}
        except Exception:
            return {}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Operator profile — the synthesized model of the user (Phase 1, A2)
    # ------------------------------------------------------------------

    def _ensure_operator_profile_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "operator_profile" not in tables:
                migration = (
                    Path(__file__).parent / "migrations" / "006_operator_profile.sql"
                )
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def save_operator_profile(
        self, profile_json: str, source: str = "llm", model: str = ""
    ) -> int:
        """Persist a new profile version. Returns the version number."""
        import time as _time

        self._ensure_operator_profile_table()
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM operator_profile WHERE agent_id=?",
                (self.agent_id,),
            ).fetchone()
            version = int(row[0]) + 1
            conn.execute(
                "INSERT INTO operator_profile "
                "(agent_id, version, created_at, source, model, profile_json) "
                "VALUES (?,?,?,?,?,?)",
                (self.agent_id, version, _time.time(), source, model, profile_json),
            )
            conn.commit()
            return version
        finally:
            conn.close()

    def get_latest_operator_profile(self) -> dict | None:
        """Return the newest profile row (or None if none synthesized yet)."""
        self._ensure_operator_profile_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM operator_profile WHERE agent_id=? "
                "ORDER BY version DESC LIMIT 1",
                (self.agent_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Practices — the declared "how I build" playbook (Layer A)
    # ------------------------------------------------------------------
    def _ensure_practices_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "practices" not in tables:
                migration = Path(__file__).parent / "migrations" / "007_practices.sql"
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def add_practice(
        self, text: str, domain: str = "global", cadence: str = "always"
    ) -> int:
        """Add a best-practice rule. Returns its id."""
        import time as _time

        self._ensure_practices_table()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO practices (agent_id, text, domain, cadence, created_at) "
                "VALUES (?,?,?,?,?)",
                (self.agent_id, text.strip(), domain, cadence, _time.time()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_practices(self, active_only: bool = True) -> list[dict]:
        """Return practices for this agent, newest first."""
        self._ensure_practices_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM practices WHERE agent_id=?"
            if active_only:
                sql += " AND active=1"
            sql += " ORDER BY id DESC"
            return [dict(r) for r in conn.execute(sql, (self.agent_id,)).fetchall()]
        finally:
            conn.close()

    def set_practice_active(self, practice_id: int, active: bool) -> None:
        self._ensure_practices_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE practices SET active=? WHERE id=? AND agent_id=?",
                (1 if active else 0, practice_id, self.agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    def record_practice_adherence(self, practice_id: int, followed: bool) -> None:
        """Tick the adherence counter for a practice (followed vs skipped)."""
        import time as _time

        self._ensure_practices_table()
        col = "times_followed" if followed else "times_skipped"
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                f"UPDATE practices SET {col}={col}+1, last_checked_at=? "
                "WHERE id=? AND agent_id=?",
                (_time.time(), practice_id, self.agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Operator runs — Fly-mode autopilot persistence (plans, steps, runs,
    # audit events, escalations). See migration 008.
    # ------------------------------------------------------------------
    def _ensure_operator_runs_tables(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            needed = {
                "plans",
                "plan_steps",
                "operator_runs",
                "run_events",
                "escalations",
            }
            if not needed.issubset(tables):
                migration = (
                    Path(__file__).parent / "migrations" / "008_operator_runs.sql"
                )
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def save_plan(
        self, goal: str, source: str = "", status: str = "pending"
    ) -> int:
        """Persist a new plan. Returns its id."""
        import time as _time

        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO plans (agent_id, goal, source, created_at, status) "
                "VALUES (?,?,?,?,?)",
                (self.agent_id, goal, source, _time.time(), status),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def save_plan_step(
        self,
        plan_id: int,
        idx: int,
        description: str,
        done_criteria: dict | str = "{}",
        depends_on: str = "",
    ) -> int:
        """Persist one step of a plan. Returns its id."""
        self._ensure_operator_runs_tables()
        criteria = (
            json.dumps(done_criteria)
            if isinstance(done_criteria, dict)
            else done_criteria
        )
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO plan_steps "
                "(plan_id, idx, description, done_criteria, depends_on) "
                "VALUES (?,?,?,?,?)",
                (plan_id, idx, description, criteria, depends_on),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_plan_steps(self, plan_id: int) -> list[dict]:
        """Return all steps for a plan, ordered by idx."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM plan_steps WHERE plan_id=? ORDER BY idx ASC",
                    (plan_id,),
                ).fetchall()
            ]
        finally:
            conn.close()

    def update_plan_step_status(
        self, step_id: int, status: str, checkpoint_sha: str = ""
    ) -> None:
        """Update a step's status (and optionally its checkpoint sha)."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            if checkpoint_sha:
                conn.execute(
                    "UPDATE plan_steps SET status=?, checkpoint_sha=? WHERE id=?",
                    (status, checkpoint_sha, step_id),
                )
            else:
                conn.execute(
                    "UPDATE plan_steps SET status=? WHERE id=?",
                    (status, step_id),
                )
            conn.commit()
        finally:
            conn.close()

    def start_run(
        self,
        plan_id: int,
        autonomy_level: str = "assisted",
        budget_usd: float = 0.0,
        worktree: str = "",
    ) -> int:
        """Open a new operator run. Returns its id."""
        import time as _time

        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO operator_runs "
                "(agent_id, plan_id, autonomy_level, budget_usd, worktree, "
                "status, started_at) VALUES (?,?,?,?,?,?,?)",
                (
                    self.agent_id,
                    plan_id,
                    autonomy_level,
                    budget_usd,
                    worktree,
                    "running",
                    _time.time(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def update_run(
        self,
        run_id: int,
        status: str | None = None,
        spent_usd: float | None = None,
        ended_at_now: bool = False,
    ) -> None:
        """Patch a run's status / spend / end time. Only sets provided fields."""
        import time as _time

        self._ensure_operator_runs_tables()
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status=?")
            params.append(status)
        if spent_usd is not None:
            sets.append("spent_usd=?")
            params.append(spent_usd)
        if ended_at_now:
            sets.append("ended_at=?")
            params.append(_time.time())
        if not sets:
            return
        params.append(run_id)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                f"UPDATE operator_runs SET {', '.join(sets)} WHERE id=?",
                tuple(params),
            )
            conn.commit()
        finally:
            conn.close()

    def add_run_event(
        self,
        run_id: int,
        type: str,
        payload: dict | str = "{}",
        step_id: int | None = None,
    ) -> int:
        """Append one event to the run's audit log. Returns its id."""
        import time as _time

        self._ensure_operator_runs_tables()
        body = json.dumps(payload) if isinstance(payload, dict) else payload
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO run_events (run_id, step_id, ts, type, payload) "
                "VALUES (?,?,?,?,?)",
                (run_id, step_id, _time.time(), type, body),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_run_events(self, run_id: int, limit: int = 200) -> list[dict]:
        """Return the run's audit log, newest first."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM run_events WHERE run_id=? "
                    "ORDER BY id DESC LIMIT ?",
                    (run_id, limit),
                ).fetchall()
            ]
        finally:
            conn.close()

    def add_escalation(
        self,
        run_id: int,
        question: str,
        context: dict | str = "{}",
        risk: float = 0.0,
        step_id: int | None = None,
    ) -> int:
        """Record a moment the operator stopped to ask the user. Returns its id."""
        import time as _time

        self._ensure_operator_runs_tables()
        ctx = json.dumps(context) if isinstance(context, dict) else context
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO escalations "
                "(run_id, step_id, ts, question, context, risk, status) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, step_id, _time.time(), question, ctx, risk, "open"),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def answer_escalation(self, escalation_id: int, user_decision: str) -> None:
        """Close an open escalation with the user's decision."""
        import time as _time

        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE escalations SET status=?, user_decision=?, answered_at=? "
                "WHERE id=?",
                ("answered", user_decision, _time.time(), escalation_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_open_escalations(self, run_id: int | None = None) -> list[dict]:
        """Return open escalations, newest first; optionally scoped to one run."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            if run_id is not None:
                rows = conn.execute(
                    "SELECT * FROM escalations WHERE status='open' AND run_id=? "
                    "ORDER BY id DESC",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM escalations WHERE status='open' "
                    "ORDER BY id DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_plan(self, plan_id: int) -> dict | None:
        """Return one plan row (id, goal, source, status), or None."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_run(self, run_id: int) -> dict | None:
        """Return one operator run row (for resume), or None."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM operator_runs WHERE id=?", (run_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_escalations(self, run_id: int | None = None, status: str | None = None,
                        limit: int = 200) -> list[dict]:
        """Return escalations, newest first, optionally filtered by run and/or status
        (open|answered). Used by resume (find the answered one) and the learner."""
        self._ensure_operator_runs_tables()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            clauses, params = [], []
            if run_id is not None:
                clauses.append("run_id=?"); params.append(run_id)
            if status is not None:
                clauses.append("status=?"); params.append(status)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM escalations{where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Calibration — the learning-loop feedback ledger (G2/G3)
    # ------------------------------------------------------------------
    def _ensure_calibration_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "calibration_events" not in tables:
                migration = Path(__file__).parent / "migrations" / "009_calibration.sql"
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def record_calibration(self, domain: str, predicted: str, was_correct: bool,
                           confidence: float = 0.0, source: str = "") -> int:
        """Record one judged-decision outcome (did the clone get it right?)."""
        import time as _time

        self._ensure_calibration_table()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO calibration_events "
                "(agent_id, domain, predicted, confidence, was_correct, ts, source) "
                "VALUES (?,?,?,?,?,?,?)",
                (self.agent_id, domain, predicted, float(confidence),
                 1 if was_correct else 0, _time.time(), source),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_calibration(self, domain: str | None = None) -> dict:
        """Per-domain calibration: {domain: {total, correct, rate}}. The honest
        'when it was confident, was it right?' signal that graduates autonomy."""
        self._ensure_calibration_table()
        conn = sqlite3.connect(self.db_path)
        try:
            if domain is not None:
                rows = conn.execute(
                    "SELECT domain, COUNT(*), SUM(was_correct) FROM calibration_events "
                    "WHERE agent_id=? AND domain=? GROUP BY domain",
                    (self.agent_id, domain),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT domain, COUNT(*), SUM(was_correct) FROM calibration_events "
                    "WHERE agent_id=? GROUP BY domain",
                    (self.agent_id,),
                ).fetchall()
            out: dict = {}
            for dom, total, correct in rows:
                total = int(total or 0)
                correct = int(correct or 0)
                out[dom] = {"total": total, "correct": correct,
                            "rate": (correct / total) if total else 0.0}
            return out
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Precedents — the Clone Resolver's "what would I do here?" memory (Loop §3)
    # ------------------------------------------------------------------
    def _ensure_precedents_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "operator_precedents" not in tables:
                migration = Path(__file__).parent / "migrations" / "010_precedents.sql"
                conn.executescript(migration.read_text())
                conn.commit()
        finally:
            conn.close()

    def add_precedent(self, category: str, blocker: str, decision: str,
                      rationale: str = "", source: str = "human_answer") -> int:
        """Record a resolved blocker so the resolver can reuse this decision later.
        Returns the precedent id. This is the write-back that compounds autonomy."""
        import time as _time

        self._ensure_precedents_table()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO operator_precedents "
                "(agent_id, category, blocker, decision, rationale, source, ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (self.agent_id, category or "general", blocker, decision,
                 rationale, source, _time.time()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def learn_from_escalation_answer(self, escalation_id: int, decision: str) -> dict:
        """Write-back: turn a human's escalation answer into a precedent (so the
        clone resolves this class next time) AND, if the clone had attempted it,
        record a calibration event (was the clone's suggestion directionally right?).
        This is the loop that makes autonomy compound. Returns what it learned."""
        rows = self.get_escalations(limit=500)
        esc = next((r for r in rows if int(r.get("id", 0)) == int(escalation_id)), None)
        if not esc:
            return {"learned": False, "reason": "escalation not found"}
        try:
            ctx = esc.get("context")
            ctx = json.loads(ctx) if isinstance(ctx, str) else (ctx or {})
        except Exception:
            ctx = {}
        category = str(ctx.get("category") or ctx.get("trigger") or "general")
        blocker = str(esc.get("question", ""))
        norm = (decision or "").strip().lower()
        # Map the human's free-text to the precedent decision vocabulary.
        decision_word = (
            "approve" if norm in ("approve", "yes", "ok", "go", "proceed", "y", "continue")
            else "skip" if norm in ("skip", "next", "ignore", "drop")
            else "takeover" if norm in ("takeover", "take over", "handover", "stop")
            else norm
        )
        pid = self.add_precedent(category, blocker, decision_word,
                                 rationale="(from your escalation answer)",
                                 source="human_answer")
        calibrated = False
        clone = ctx.get("clone_attempt") or {}
        if clone:
            clone_dec = str(clone.get("decision", ""))
            was_correct = (clone_dec == decision_word)
            try:
                self.record_calibration(category, clone_dec, was_correct,
                                        confidence=float(clone.get("confidence", 0.0)),
                                        source="escalation_answer")
                calibrated = True
            except Exception:
                pass
        return {"learned": True, "precedent_id": pid, "category": category,
                "decision": decision_word, "calibrated": calibrated}

    def get_precedents(self, category: str | None = None, limit: int = 100) -> list[dict]:
        """Return precedents for this agent, newest first, optionally scoped to a
        category. The resolver ranks these by similarity to the live blocker."""
        self._ensure_precedents_table()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            if category is not None:
                rows = conn.execute(
                    "SELECT * FROM operator_precedents WHERE agent_id=? AND category=? "
                    "ORDER BY id DESC LIMIT ?",
                    (self.agent_id, category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM operator_precedents WHERE agent_id=? "
                    "ORDER BY id DESC LIMIT ?",
                    (self.agent_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Setup Agent — observations, config, changes (M3)
    # ------------------------------------------------------------------

    def log_setup_observation(
        self,
        tool_name: str,
        tool_input: str,
        routing_confidence: float,
        outcome_signal: str = "unknown",
    ) -> None:
        """Log one PostToolUse observation to the rolling window."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO setup_observations "
                "(agent_id, org_id, tool_name, tool_input, routing_confidence, outcome_signal, observed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (self.agent_id, self.org_id, tool_name, tool_input[:500],
                 routing_confidence, outcome_signal, ts),
            )
            conn.commit()
            conn.execute(
                "DELETE FROM setup_observations WHERE id NOT IN ("
                "  SELECT id FROM setup_observations ORDER BY id DESC LIMIT 200"
                ")"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("log_setup_observation failed: %s", exc)

    def get_setup_observations(self, limit: int = 50) -> list[dict]:
        """Return the most recent N setup observations."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM setup_observations WHERE agent_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (self.agent_id, limit),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            logger.debug("get_setup_observations failed", exc_info=True)
            return []

    def get_setup_config(self, key: str, default: str = "") -> str:
        """Get a setup config value by key."""
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT config_value FROM setup_config WHERE agent_id=? AND org_id=? AND config_key=?",
                (self.agent_id, self.org_id, key),
            ).fetchone()
            conn.close()
            return row[0] if row else default
        except Exception:
            return default

    def set_setup_config(self, key: str, value: str) -> None:
        """Set a setup config value."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO setup_config (agent_id, org_id, config_key, config_value, updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(agent_id, org_id, config_key) "
                "DO UPDATE SET config_value=excluded.config_value, updated_at=excluded.updated_at",
                (self.agent_id, self.org_id, key, value, ts),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("set_setup_config failed: %s", exc)

    def apply_setup_change(
        self,
        change_type: str,
        description: str,
        old_value: dict,
        new_value: dict,
        revert_payload: dict,
        autonomy_stage: int = 1,
    ) -> int:
        """Record a setup change and return its row ID."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                "INSERT INTO setup_changes "
                "(agent_id, org_id, change_type, description, old_value, new_value, "
                "revert_payload, applied_at, autonomy_stage) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (self.agent_id, self.org_id, change_type, description,
                 json.dumps(old_value), json.dumps(new_value),
                 json.dumps(revert_payload), ts, autonomy_stage),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception as exc:
            logger.debug("apply_setup_change failed: %s", exc)
            return -1

    def revert_setup_change(self, change_id: int) -> bool:
        """Mark a change as reverted."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                "UPDATE setup_changes SET reverted_at=? WHERE id=? AND agent_id=?",
                (ts, change_id, self.agent_id),
            )
            rowcount = cur.rowcount
            conn.commit()
            conn.close()
            return rowcount > 0
        except Exception:
            return False

    def get_setup_changes(
        self,
        limit: int = 50,
        include_reverted: bool = True,
    ) -> list[dict]:
        """Return setup changes, most recent first."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            where = "WHERE agent_id=?"
            params: list = [self.agent_id]
            if not include_reverted:
                where += " AND reverted_at IS NULL"
            rows = conn.execute(
                f"SELECT * FROM setup_changes {where} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_setup_change_by_id(self, change_id: int) -> dict | None:
        """Return a single setup change by ID, or None if not found."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM setup_changes WHERE id=? AND agent_id=?",
                (change_id, self.agent_id),
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception:
            logger.debug("get_setup_change_by_id failed", exc_info=True)
            return None
