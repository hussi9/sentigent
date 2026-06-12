"""Event system for Sentigent — enables webhooks, callbacks, and integrations.

Sentigent fires events at key moments in the judgment lifecycle:
- on_escalation: when a decision is escalated to human review
- on_policy_violation: when a policy is violated
- on_circuit_breaker: when memory circuit breaker opens/closes
- on_outcome: when an outcome is recorded
- on_pattern_discovered: when a new procedural rule is mined
- on_drift_detected: when baseline drift is detected
- on_judgment_milestone: when judgment score crosses a threshold

Handlers can be:
1. Sync Python callbacks (in-process)
2. Webhook URLs (HTTP POST, fire-and-forget)

All handler invocations are exception-safe: one handler failing
never blocks evaluate() or other handlers.

Usage:
    from sentigent.events import get_event_bus, SentigentEvent, EVENT_ESCALATION

    bus = get_event_bus()

    # Callback handler
    bus.on("escalation", my_slack_notifier)

    # Webhook handler
    bus.add_webhook("escalation", "https://hooks.slack.com/...")

    # Events are fired automatically by Sentigent engine — no manual emit needed
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger("sentigent.events")


# ── Event Types ───────────────────────────────────────────────────────

EVENT_ESCALATION = "escalation"
EVENT_POLICY_VIOLATION = "policy_violation"
EVENT_CIRCUIT_BREAKER = "circuit_breaker"
EVENT_OUTCOME = "outcome"
EVENT_PATTERN_DISCOVERED = "pattern_discovered"
EVENT_DRIFT_DETECTED = "drift_detected"
EVENT_JUDGMENT_MILESTONE = "judgment_milestone"

ALL_EVENT_TYPES = (
    EVENT_ESCALATION,
    EVENT_POLICY_VIOLATION,
    EVENT_CIRCUIT_BREAKER,
    EVENT_OUTCOME,
    EVENT_PATTERN_DISCOVERED,
    EVENT_DRIFT_DETECTED,
    EVENT_JUDGMENT_MILESTONE,
)


# ── Event Model ───────────────────────────────────────────────────────


class SentigentEvent(BaseModel):
    """Structured event payload for all Sentigent events.

    Serializable to JSON for webhook delivery.
    """

    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str = ""
    agent_id: str = ""
    action: str = ""
    reason: str = ""
    signals: dict[str, float] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string for webhook payload."""
        return self.model_dump_json()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return self.model_dump(mode="json")


# ── Webhook Dispatcher ────────────────────────────────────────────────


class WebhookDispatcher:
    """Fire-and-forget HTTP POST dispatcher for webhook URLs.

    Uses urllib.request (stdlib, zero external deps) with a daemon thread
    and queue for non-blocking dispatch. Retries once on failure.
    Logs errors, never raises.

    Usage:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch("https://hooks.slack.com/...", {"event": "escalation"})
        # Returns immediately; POST happens in background
    """

    def __init__(self, max_queue_size: int = 100) -> None:
        self._queue: queue.Queue[tuple[str, dict, dict[str, str] | None]] = queue.Queue(
            maxsize=max_queue_size,
        )
        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="sentigent-webhook-dispatcher",
        )
        self._thread.start()

    def dispatch(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue a webhook POST for background delivery.

        Non-blocking. If queue is full, the payload is dropped (logged).

        Args:
            url: Webhook URL
            payload: JSON-serializable dict
            headers: Optional extra HTTP headers
        """
        try:
            self._queue.put_nowait((url, payload, headers))
        except queue.Full:
            logger.warning("Webhook queue full, dropping payload for %s", url)

    def _worker(self) -> None:
        """Background worker that drains the queue and sends POSTs."""
        while self._running:
            try:
                url, payload, headers = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            self._send_with_retry(url, payload, headers)
            self._queue.task_done()

    def _send_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        max_retries: int = 1,
    ) -> None:
        """Send HTTP POST with one retry on failure."""
        all_headers = {
            "Content-Type": "application/json",
            "User-Agent": "Sentigent-Webhook/0.1",
        }
        if headers:
            all_headers.update(headers)

        data = json.dumps(payload, default=str).encode("utf-8")

        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=data, headers=all_headers, method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    logger.debug(
                        "Webhook delivered to %s (status=%d)", url, resp.status,
                    )
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if attempt < max_retries:
                    logger.debug("Webhook retry %d for %s: %s", attempt + 1, url, exc)
                else:
                    logger.warning("Webhook delivery failed for %s: %s", url, exc)

    def shutdown(self) -> None:
        """Stop the worker thread. Pending webhooks may be dropped."""
        self._running = False
        self._thread.join(timeout=5.0)


# ── Event Bus ─────────────────────────────────────────────────────────


class EventBus:
    """Central event dispatcher with sync callbacks and webhook support.

    Thread-safe. All handler invocations are exception-isolated —
    one handler failing never blocks other handlers or the caller.

    Usage:
        bus = EventBus()
        bus.on("escalation", my_handler)
        bus.add_webhook("escalation", "https://hooks.slack.com/...")
        bus.emit("escalation", SentigentEvent(event_type="escalation", ...))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[SentigentEvent], None]]] = {}
        self._webhooks: dict[str, list[tuple[str, dict[str, str] | None]]] = {}
        self._dispatcher = WebhookDispatcher()
        self._lock = threading.Lock()

    def on(
        self,
        event_type: str,
        handler: Callable[[SentigentEvent], None],
    ) -> None:
        """Register a synchronous callback for an event type.

        The handler receives a SentigentEvent and should return None.
        Exceptions in handlers are caught and logged.

        Args:
            event_type: Event type to listen for (e.g., "escalation")
            handler: Callable that takes a SentigentEvent
        """
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def remove_handler(
        self,
        event_type: str,
        handler: Callable[[SentigentEvent], None],
    ) -> None:
        """Unregister a handler.

        Args:
            event_type: Event type to unregister from
            handler: The handler to remove
        """
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass  # Handler not found, safe to ignore

    def add_webhook(
        self,
        event_type: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Register a webhook URL for an event type.

        When the event fires, Sentigent will HTTP POST a JSON payload to the URL.

        Args:
            event_type: Event type to subscribe to
            url: Webhook URL to POST to
            headers: Optional extra HTTP headers to include
        """
        with self._lock:
            if event_type not in self._webhooks:
                self._webhooks[event_type] = []
            self._webhooks[event_type].append((url, headers))

    def remove_webhook(self, event_type: str, url: str) -> None:
        """Unregister a webhook URL.

        Args:
            event_type: Event type to unregister from
            url: The URL to remove
        """
        with self._lock:
            if event_type in self._webhooks:
                self._webhooks[event_type] = [
                    (u, h) for u, h in self._webhooks[event_type] if u != url
                ]

    def emit(self, event_type: str, event: SentigentEvent) -> None:
        """Fire an event. Calls all registered handlers and webhooks.

        Handlers are called synchronously in registration order.
        Webhooks are dispatched to a background thread (fire-and-forget).
        Exceptions in handlers are caught and logged, never propagated.

        Args:
            event_type: The event type being fired
            event: The event payload
        """
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            webhooks = list(self._webhooks.get(event_type, []))

        # Invoke sync callbacks
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.warning(
                    "Event handler %s failed for %s: %s",
                    getattr(handler, "__name__", repr(handler)),
                    event_type,
                    exc,
                )

        # Dispatch webhooks (non-blocking)
        if webhooks:
            payload = event.to_dict()
            for url, headers in webhooks:
                self._dispatcher.dispatch(url, payload, headers)

    def shutdown(self) -> None:
        """Stop the webhook dispatcher."""
        self._dispatcher.shutdown()

    def clear(self) -> None:
        """Remove all handlers and webhooks. Primarily for testing."""
        with self._lock:
            self._handlers.clear()
            self._webhooks.clear()


# ── Singleton Management ──────────────────────────────────────────────

_event_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the global EventBus singleton.

    Creates a new EventBus on first call. Thread-safe.

    Returns:
        The global EventBus instance.
    """
    global _event_bus
    with _bus_lock:
        if _event_bus is None:
            _event_bus = EventBus()
        return _event_bus


def reset_event_bus() -> None:
    """Reset the global EventBus singleton. Primarily for testing."""
    global _event_bus
    with _bus_lock:
        if _event_bus is not None:
            _event_bus.shutdown()
            _event_bus = None
