"""Tests for the observability module (SERIOUS 4.4).

Covers:
- SentigentMetrics counter operations
- Latency recording and histogram
- Snapshot format
- NoOpMetrics zero-overhead behavior
- SpanContext timing
- structured_log JSON format
- get_metrics() singleton behavior
"""

import json
import logging
import time

import pytest

from sentigent.observability import (
    NoOpMetrics,
    SentigentMetrics,
    SpanContext,
    get_metrics,
    reset_metrics,
    structured_log,
)


class TestSentigentMetrics:

    def test_increment_basic(self) -> None:
        """Counter increments correctly."""
        m = SentigentMetrics()
        m.increment("decisions_total")
        m.increment("decisions_total")
        m.increment("decisions_total")
        snap = m.snapshot()
        assert snap["counters"]["decisions_total"] == 3

    def test_increment_with_labels(self) -> None:
        """Labeled counters are tracked separately."""
        m = SentigentMetrics()
        m.increment("decisions_total", {"action": "proceed"})
        m.increment("decisions_total", {"action": "proceed"})
        m.increment("decisions_total", {"action": "escalate"})
        snap = m.snapshot()
        assert snap["counters"]["decisions_total{action=proceed}"] == 2
        assert snap["counters"]["decisions_total{action=escalate}"] == 1

    def test_record_latency(self) -> None:
        """Latency values are recorded and statistics computed."""
        m = SentigentMetrics()
        for val in [10.0, 20.0, 30.0, 40.0, 50.0]:
            m.record_latency("evaluate_latency_ms", val)
        snap = m.snapshot()
        assert snap["latency_stats"]["count"] == 5
        assert snap["latency_stats"]["mean"] == 30.0
        assert snap["latency_stats"]["min"] == 10.0
        assert snap["latency_stats"]["max"] == 50.0
        assert snap["latency_stats"]["p50"] > 0

    def test_snapshot_format(self) -> None:
        """Snapshot returns expected dict structure."""
        m = SentigentMetrics()
        snap = m.snapshot()
        assert "counters" in snap
        assert "latency_stats" in snap
        assert isinstance(snap["counters"], dict)
        assert isinstance(snap["latency_stats"], dict)

    def test_snapshot_empty_latency(self) -> None:
        """Empty latency stats returns empty dict."""
        m = SentigentMetrics()
        snap = m.snapshot()
        assert snap["latency_stats"] == {}

    def test_reset(self) -> None:
        """Reset clears all counters and latencies."""
        m = SentigentMetrics()
        m.increment("foo")
        m.record_latency("bar", 10.0)
        m.reset()
        snap = m.snapshot()
        assert snap["counters"] == {}
        assert snap["latency_stats"] == {}


class TestNoOpMetrics:

    def test_noop_increment(self) -> None:
        """NoOpMetrics.increment() does nothing and doesn't raise."""
        m = NoOpMetrics()
        m.increment("anything", {"label": "value"})
        # No assertion needed — just verifying no exception

    def test_noop_record_latency(self) -> None:
        """NoOpMetrics.record_latency() does nothing."""
        m = NoOpMetrics()
        m.record_latency("anything", 42.0)

    def test_noop_snapshot_empty(self) -> None:
        """NoOpMetrics.snapshot() returns empty structure."""
        m = NoOpMetrics()
        snap = m.snapshot()
        assert snap == {"counters": {}, "latency_stats": {}}

    def test_noop_reset(self) -> None:
        """NoOpMetrics.reset() does nothing."""
        m = NoOpMetrics()
        m.reset()


class TestSpanContext:

    def test_span_records_duration(self) -> None:
        """SpanContext records duration in milliseconds."""
        metrics = SentigentMetrics()
        with SpanContext("test_op", metrics) as span:
            time.sleep(0.01)  # 10ms
        assert span.duration_ms > 5.0  # Should be >= ~10ms
        assert span.duration_ms < 500.0  # Shouldn't be absurdly long

    def test_span_records_to_metrics(self) -> None:
        """SpanContext records latency to metrics on exit."""
        metrics = SentigentMetrics()
        with SpanContext("eval", metrics):
            pass
        snap = metrics.snapshot()
        assert snap["latency_stats"]["count"] == 1

    def test_span_attributes(self) -> None:
        """SpanContext can store attributes."""
        metrics = SentigentMetrics()
        with SpanContext("test", metrics) as span:
            span.set_attribute("agent_id", "test_agent")
            span.set_attribute("action", "proceed")
        assert span.attributes["agent_id"] == "test_agent"
        assert span.attributes["action"] == "proceed"

    def test_span_exception_records_error(self) -> None:
        """SpanContext records error attributes on exception."""
        metrics = SentigentMetrics()
        with pytest.raises(ValueError):
            with SpanContext("test", metrics) as span:
                raise ValueError("test error")
        assert span.attributes.get("error") is True
        assert span.attributes.get("error_type") == "ValueError"


class TestStructuredLog:

    def test_structured_log_json_format(self, caplog) -> None:
        """structured_log emits valid JSON."""
        test_logger = logging.getLogger("test.structured")
        with caplog.at_level(logging.INFO, logger="test.structured"):
            structured_log(
                test_logger, logging.INFO, "test_event",
                action="proceed", confidence=0.87,
            )
        assert len(caplog.records) == 1
        data = json.loads(caplog.records[0].message)
        assert data["event"] == "test_event"
        assert data["action"] == "proceed"
        assert data["confidence"] == 0.87
        assert "ts" in data

    def test_structured_log_includes_timestamp(self, caplog) -> None:
        """Timestamp is present and ISO-formatted."""
        test_logger = logging.getLogger("test.structured2")
        with caplog.at_level(logging.INFO, logger="test.structured2"):
            structured_log(test_logger, logging.INFO, "check_ts")
        data = json.loads(caplog.records[0].message)
        assert "T" in data["ts"]  # ISO format has 'T' separator


class TestGetMetrics:

    def test_get_metrics_disabled_returns_noop(self) -> None:
        """get_metrics() returns NoOpMetrics when metrics_enabled=False."""
        from sentigent.config import SentigentConfig, set_config

        reset_metrics()
        set_config(SentigentConfig(metrics_enabled=False))
        m = get_metrics()
        assert isinstance(m, NoOpMetrics)
        set_config(None)
        reset_metrics()

    def test_get_metrics_enabled_returns_real(self) -> None:
        """get_metrics() returns SentigentMetrics when metrics_enabled=True."""
        from sentigent.config import SentigentConfig, set_config

        reset_metrics()
        set_config(SentigentConfig(metrics_enabled=True))
        m = get_metrics()
        assert isinstance(m, SentigentMetrics)
        set_config(None)
        reset_metrics()
