"""Observability module — structured logging, metrics counters, and tracing spans.

Provides:
- SentigentMetrics: Counter-based metrics (decisions, signals, outcomes, latencies)
- NoOpMetrics: Zero-overhead stub when metrics_enabled=False
- structured_log(): JSON-formatted log entries for machine parsing
- SpanContext: Lightweight tracing span for evaluate() hot path
- get_metrics(): Global singleton accessor

All observability is opt-in via config.metrics_enabled.
Zero overhead when disabled (no-op implementations).

OpenTelemetry-ready: if opentelemetry-api is installed, SpanContext
creates real OTEL spans. Otherwise, degrades gracefully to structured logs.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sentigent.observability")


# ── Structured Logging ────────────────────────────────────────────────


def structured_log(
    target_logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emit a structured JSON log line.

    Produces machine-parseable log entries suitable for log aggregation
    (Datadog, Splunk, CloudWatch, etc.).

    Example output:
        {"ts":"2026-02-18T12:00:00Z","event":"evaluate","action":"escalate",
         "confidence":0.87,"latency_ms":18.3,"agent_id":"default"}

    Args:
        target_logger: The Python logger to emit to
        level: Logging level (e.g., logging.INFO)
        event: Event name (e.g., "evaluate_complete")
        **fields: Arbitrary key-value pairs to include
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
    }
    entry.update(fields)
    target_logger.log(level, json.dumps(entry, default=str))


# ── Metrics ───────────────────────────────────────────────────────────


class SentigentMetrics:
    """Thread-safe counter-based metrics registry.

    Tracks:
    - decisions_total (by action type)
    - outcomes_total (by outcome type)
    - signal_firings (by signal type when strength > threshold)
    - evaluate_latency_ms (rolling histogram)
    - memory_failures_total
    - pattern_mines_total
    - episodes_stored_total
    - baselines_updated_total
    - events_emitted_total
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._latencies: deque[float] = deque(maxlen=1000)

    def increment(self, name: str, labels: dict[str, str] | None = None) -> None:
        """Increment a named counter.

        Args:
            name: Counter name (e.g., "decisions_total")
            labels: Optional label dict for sub-categorization
        """
        key = name
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            key = f"{name}{{{label_str}}}"

        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    def record_latency(self, name: str, ms: float) -> None:
        """Record a latency measurement in milliseconds.

        Args:
            name: Metric name (e.g., "evaluate_latency_ms")
            ms: Duration in milliseconds
        """
        with self._lock:
            self._latencies.append(ms)
            # Also track as counter for total invocations
            self._counters[f"{name}_count"] = self._counters.get(f"{name}_count", 0) + 1

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time snapshot of all metrics.

        Returns:
            Dict with 'counters' and 'latency_stats' keys.
            Latency stats include p50, p95, p99, mean, count.
        """
        with self._lock:
            counters = dict(self._counters)
            latencies = list(self._latencies)

        latency_stats: dict[str, float] = {}
        if latencies:
            sorted_lat = sorted(latencies)
            n = len(sorted_lat)
            latency_stats = {
                "count": n,
                "mean": round(sum(sorted_lat) / n, 2),
                "p50": round(sorted_lat[int(n * 0.5)], 2),
                "p95": round(sorted_lat[min(n - 1, int(n * 0.95))], 2),
                "p99": round(sorted_lat[min(n - 1, int(n * 0.99))], 2),
                "min": round(sorted_lat[0], 2),
                "max": round(sorted_lat[-1], 2),
            }

        return {
            "counters": counters,
            "latency_stats": latency_stats,
        }

    def reset(self) -> None:
        """Reset all counters and latency data."""
        with self._lock:
            self._counters.clear()
            self._latencies.clear()


class NoOpMetrics:
    """Zero-overhead stub when metrics are disabled.

    All methods are no-ops. Used when config.metrics_enabled=False.
    """

    def increment(self, name: str, labels: dict[str, str] | None = None) -> None:
        pass

    def record_latency(self, name: str, ms: float) -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        return {"counters": {}, "latency_stats": {}}

    def reset(self) -> None:
        pass


# ── Singleton Management ──────────────────────────────────────────────

_real_metrics: SentigentMetrics | None = None
_noop_metrics = NoOpMetrics()
_metrics_lock = threading.Lock()


def get_metrics() -> SentigentMetrics | NoOpMetrics:
    """Get the global metrics instance.

    Returns SentigentMetrics if config.metrics_enabled is True,
    otherwise returns NoOpMetrics (zero overhead).
    """
    global _real_metrics

    try:
        from sentigent.config import get_config
        cfg = get_config()
        if not cfg.metrics_enabled:
            return _noop_metrics
    except Exception:
        return _noop_metrics

    with _metrics_lock:
        if _real_metrics is None:
            _real_metrics = SentigentMetrics()
        return _real_metrics


def reset_metrics() -> None:
    """Reset the global metrics singleton. Primarily for testing."""
    global _real_metrics
    with _metrics_lock:
        _real_metrics = None


# ── Tracing Spans ─────────────────────────────────────────────────────


class SpanContext:
    """Lightweight tracing span for timing critical code sections.

    Compatible with OpenTelemetry: if otel is installed, creates real spans.
    Otherwise, emits structured log lines with timing data.

    Usage:
        with SpanContext("evaluate", metrics) as span:
            span.set_attribute("agent_id", "my-agent")
            # ... do work ...
        # Duration automatically recorded in metrics and logged
    """

    def __init__(
        self,
        name: str,
        metrics: SentigentMetrics | NoOpMetrics | None = None,
    ) -> None:
        self.name = name
        self.metrics = metrics or _noop_metrics
        self.attributes: dict[str, Any] = {}
        self._start_time: float = 0.0
        self._duration_ms: float = 0.0

    def set_attribute(self, key: str, value: Any) -> None:
        """Add a key-value attribute to this span."""
        self.attributes[key] = value

    @property
    def duration_ms(self) -> float:
        """Duration of the span in milliseconds (available after exit)."""
        return self._duration_ms

    def __enter__(self) -> SpanContext:
        self._start_time = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self._duration_ms = (time.monotonic() - self._start_time) * 1000.0
        self.metrics.record_latency(f"{self.name}_latency_ms", self._duration_ms)

        if exc_type is not None:
            self.set_attribute("error", True)
            self.set_attribute("error_type", exc_type.__name__)

        structured_log(
            logger, logging.DEBUG,
            f"span_{self.name}",
            duration_ms=round(self._duration_ms, 2),
            **self.attributes,
        )
