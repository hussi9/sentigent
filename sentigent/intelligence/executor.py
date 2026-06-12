"""
ActionExecutor — makes evaluate() decisions concrete.

When engine.evaluate() returns a Decision, the executor translates the
abstract action into real side-effects:

  escalate   → fires EventBus escalation event + optional webhook notification
  slow_down  → configurable delay (default 500 ms) + warning log
  enrich     → auto-fetches peer patterns + similar episodes from hub
  proceed    → fast path — no-op

Each action type has a built-in plugin that runs by default. Additional
plugins can be registered at runtime (e.g., Slack notifier, PagerDuty).

Design principles:
  - Fails open: executor errors NEVER propagate to the caller
  - Pluggable: register custom plugins per action type
  - Observable: latency + result logged per execution
  - Lightweight: executor is fire-and-forget in the hot path

Usage:
    from sentigent.intelligence.executor import get_executor
    executor = get_executor()

    # After evaluate():
    result = executor.execute(decision, agent_id=agent_id, task=task)
    # result.enriched_context can be merged into next evaluate() context
"""
from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    """Everything the executor knows about a decision that needs acting on."""
    action: str                       # proceed | slow_down | enrich | escalate
    agent_id: str
    task: str
    trace_id: str
    confidence: float
    signals: dict[str, float]
    reason: str
    context: dict[str, Any] = field(default_factory=dict)
    org_id: str = ""


@dataclass
class ExecutionResult:
    """What the executor did in response to a decision."""
    action: str
    latency_ms: float
    plugins_run: list[str] = field(default_factory=list)
    enriched_context: dict[str, Any] = field(default_factory=dict)
    slow_down_ms: float = 0.0
    escalation_fired: bool = False
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Plugin protocol
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class ActionPlugin(Protocol):
    """Protocol for executor plugins. Register per action type."""

    @property
    def name(self) -> str: ...

    def can_handle(self, action: str) -> bool: ...

    def execute(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        """Execute side-effects. Mutate `result` in place. Must not raise."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Built-in plugins
# ─────────────────────────────────────────────────────────────────────────────

class SlowDownPlugin:
    """Introduces a configurable delay for slow_down decisions."""

    name = "slow_down"
    _DEFAULT_DELAY_MS = 500

    def __init__(self, delay_ms: int = _DEFAULT_DELAY_MS) -> None:
        self._delay_s = delay_ms / 1000

    def can_handle(self, action: str) -> bool:
        return action == "slow_down"

    def execute(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        time.sleep(self._delay_s)
        result.slow_down_ms = self._delay_s * 1000
        logger.warning(
            "[executor] slow_down — agent=%s trace=%s delay=%.0fms reason=%s",
            ctx.agent_id, ctx.trace_id, result.slow_down_ms, ctx.reason[:80],
        )


class EscalatePlugin:
    """Fires the EventBus escalation event and all registered webhooks."""

    name = "escalate"

    def can_handle(self, action: str) -> bool:
        return action == "escalate"

    def execute(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        try:
            from sentigent.events import get_event_bus, SentigentEvent, EVENT_ESCALATION
            bus = get_event_bus()
            event = SentigentEvent(
                event_type=EVENT_ESCALATION,
                trace_id=ctx.trace_id,
                agent_id=ctx.agent_id,
                action=ctx.action,
                reason=ctx.reason,
                signals=ctx.signals,
                context=ctx.context,
                metadata={
                    "task": ctx.task[:200],
                    "confidence": ctx.confidence,
                    "org_id": ctx.org_id,
                },
            )
            bus.emit(EVENT_ESCALATION, event)
            result.escalation_fired = True
            logger.warning(
                "[executor] escalation fired — agent=%s trace=%s reason=%s",
                ctx.agent_id, ctx.trace_id, ctx.reason[:120],
            )
        except Exception as exc:
            logger.debug("EscalatePlugin failed: %s", exc)
            result.error = str(exc)


class EnrichPlugin:
    """Fetches peer patterns + similar episodes from hub to enrich context."""

    name = "enrich"

    def can_handle(self, action: str) -> bool:
        return action == "enrich"

    def execute(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        enriched: dict[str, Any] = {}
        try:
            from sentigent.intelligence.hub import get_hub
            hub = get_hub(org_id=ctx.org_id)
            patterns = hub.get_peer_patterns(limit=5)
            if patterns:
                enriched["peer_patterns"] = patterns
                logger.debug(
                    "[executor] enrich — %d peer patterns fetched for agent=%s",
                    len(patterns), ctx.agent_id,
                )
        except Exception as exc:
            logger.debug("EnrichPlugin peer-patterns failed: %s", exc)

        result.enriched_context = enriched


class ProceedPlugin:
    """No-op fast path for proceed decisions."""

    name = "proceed"

    def can_handle(self, action: str) -> bool:
        return action == "proceed"

    def execute(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        pass  # deliberate no-op


# ─────────────────────────────────────────────────────────────────────────────
# Executor
# ─────────────────────────────────────────────────────────────────────────────

class ActionExecutor:
    """
    Executes concrete side-effects for decisions from evaluate().

    Built-in plugins handle all 4 action types. Register additional plugins
    for custom notifications (Slack, PagerDuty, JIRA, etc.).

    All executions are exception-safe and non-blocking in the hot path.
    """

    def __init__(self) -> None:
        self._plugins: list[ActionPlugin] = []
        self._lock = threading.Lock()
        self._stats: dict[str, dict[str, float]] = {}  # action → {count, total_ms}

        # Register built-in plugins
        for plugin in [ProceedPlugin(), SlowDownPlugin(), EscalatePlugin(), EnrichPlugin()]:
            self.register_plugin(plugin)

    def register_plugin(self, plugin: ActionPlugin) -> None:
        """Add a custom plugin. Plugins are tried in registration order."""
        with self._lock:
            self._plugins.append(plugin)

    def execute(
        self,
        action: str,
        agent_id: str,
        task: str,
        trace_id: str,
        confidence: float = 0.5,
        signals: dict[str, float] | None = None,
        reason: str = "",
        context: dict[str, Any] | None = None,
        org_id: str = "",
    ) -> ExecutionResult:
        """
        Execute the action's side-effects. Always returns an ExecutionResult.

        Never raises — all errors are captured in result.error.

        Returns:
            ExecutionResult with what happened (enriched_context, latency, etc.)
        """
        t0 = time.monotonic()
        ctx = ExecutionContext(
            action=action,
            agent_id=agent_id,
            task=task,
            trace_id=trace_id,
            confidence=confidence,
            signals=signals or {},
            reason=reason,
            context=context or {},
            org_id=org_id,
        )
        result = ExecutionResult(action=action, latency_ms=0.0)

        with self._lock:
            plugins = [p for p in self._plugins if p.can_handle(action)]

        for plugin in plugins:
            try:
                plugin.execute(ctx, result)
                result.plugins_run.append(plugin.name)
            except Exception as exc:
                logger.debug("Plugin %s failed: %s", plugin.name, exc)
                result.error = str(exc)

        result.latency_ms = (time.monotonic() - t0) * 1000
        self._record_stat(action, result.latency_ms)

        if action not in ("proceed",):
            logger.debug(
                "[executor] action=%s agent=%s latency=%.1fms plugins=%s",
                action, agent_id, result.latency_ms, result.plugins_run,
            )

        return result

    def get_stats(self) -> dict[str, dict[str, float]]:
        """Return execution stats per action type."""
        with self._lock:
            return {k: dict(v) for k, v in self._stats.items()}

    def _record_stat(self, action: str, latency_ms: float) -> None:
        with self._lock:
            s = self._stats.setdefault(action, {"count": 0, "total_ms": 0.0})
            s["count"] += 1
            s["total_ms"] += latency_ms


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_executor_lock = threading.Lock()
_executor_instance: ActionExecutor | None = None


def get_executor() -> ActionExecutor:
    """Return the singleton ActionExecutor."""
    global _executor_instance
    with _executor_lock:
        if _executor_instance is None:
            _executor_instance = ActionExecutor()
        return _executor_instance
