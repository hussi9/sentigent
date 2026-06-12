"""Async wrapper for Sentigent — enables non-blocking evaluation in async frameworks.

Provides AsyncSentigent that wraps the synchronous Sentigent engine with
async-compatible interfaces. Uses asyncio.to_thread() for SQLite operations
to avoid blocking the event loop.

Usage:
    from sentigent.core.async_engine import AsyncSentigent

    judge = AsyncSentigent(profile="financial_ops")
    decision = await judge.evaluate(
        task="Process refund for $50,000",
        context={"amount": 50000},
    )
    await judge.record_outcome(decision.trace_id, "correct")
"""

from __future__ import annotations

import asyncio
from typing import Any

from sentigent.core.engine import Sentigent
from sentigent.core.types import Decision, Profile


class AsyncSentigent:
    """Async wrapper around Sentigent for use in async frameworks.

    All database operations are run in a thread pool to avoid blocking
    the event loop. Signal computation is pure CPU and fast enough to
    run synchronously.

    Works with:
    - LangGraph async nodes
    - FastAPI / Starlette
    - OpenAI Agents SDK (async)
    - Any asyncio-based agent framework
    """

    def __init__(
        self,
        profile: str | Profile = "default",
        agent_id: str | None = None,
        org_id: str | None = None,
        db_path: str | None = None,
        evaluate_timeout_ms: int = 50,
    ) -> None:
        """Initialize with the same parameters as Sentigent."""
        self._sync = Sentigent(
            profile=profile,
            agent_id=agent_id,
            org_id=org_id,
            db_path=db_path,
            evaluate_timeout_ms=evaluate_timeout_ms,
        )

    @property
    def judgment_score(self) -> float:
        """Current judgment accuracy score (synchronous, fast)."""
        return self._sync.judgment_score

    async def evaluate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> Decision:
        """Async evaluate — runs in thread pool to avoid blocking event loop.

        Same interface as Sentigent.evaluate() but async.
        """
        return await asyncio.to_thread(
            self._sync.evaluate,
            task=task,
            context=context,
            agent_state=agent_state,
        )

    async def record_outcome(
        self,
        trace_id: str,
        outcome: str,
        feedback: str | None = None,
    ) -> None:
        """Async record_outcome — runs DB write in thread pool."""
        await asyncio.to_thread(
            self._sync.record_outcome,
            trace_id=trace_id,
            outcome=outcome,
            feedback=feedback,
        )

    async def prune_episodes(self, ttl_days: int = 90) -> int:
        """Async episode pruning."""
        return await asyncio.to_thread(
            self._sync._memory.prune_old_episodes,
            ttl_days=ttl_days,
        )
