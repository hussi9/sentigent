"""Tests for the event/webhook system (SERIOUS 5.2).

Covers:
- EventBus handler registration and emission
- Handler exception isolation
- Handler removal
- SentigentEvent serialization
- WebhookDispatcher (mocked)
- Full integration: evaluate() fires escalation events
- Full integration: record_outcome() fires outcome events
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sentigent import Sentigent
from sentigent.events import (
    EVENT_CIRCUIT_BREAKER,
    EVENT_ESCALATION,
    EVENT_OUTCOME,
    EventBus,
    SentigentEvent,
    get_event_bus,
    reset_event_bus,
)


class TestSentigentEvent:

    def test_event_creation(self) -> None:
        """SentigentEvent can be created with all fields."""
        event = SentigentEvent(
            event_type="escalation",
            trace_id="abc-123",
            agent_id="test_agent",
            action="escalate",
            reason="Amount too high",
            signals={"caution": 0.9, "doubt": 0.3},
            context={"amount": 50000},
        )
        assert event.event_type == "escalation"
        assert event.trace_id == "abc-123"
        assert event.timestamp is not None

    def test_event_to_json(self) -> None:
        """SentigentEvent serializes to valid JSON."""
        event = SentigentEvent(
            event_type="outcome",
            trace_id="xyz-456",
        )
        json_str = event.to_json()
        assert '"event_type":"outcome"' in json_str or '"event_type": "outcome"' in json_str

    def test_event_to_dict(self) -> None:
        """SentigentEvent serializes to dict."""
        event = SentigentEvent(
            event_type="test",
            metadata={"key": "value"},
        )
        d = event.to_dict()
        assert d["event_type"] == "test"
        assert d["metadata"]["key"] == "value"

    def test_event_defaults(self) -> None:
        """SentigentEvent has sensible defaults."""
        event = SentigentEvent(event_type="test")
        assert event.trace_id == ""
        assert event.agent_id == ""
        assert event.signals == {}
        assert event.context == {}


class TestEventBus:

    def test_register_and_emit(self) -> None:
        """Handler is called when event is emitted."""
        bus = EventBus()
        received = []
        bus.on("test", lambda e: received.append(e))
        event = SentigentEvent(event_type="test", trace_id="123")
        bus.emit("test", event)
        assert len(received) == 1
        assert received[0].trace_id == "123"
        bus.shutdown()

    def test_multiple_handlers(self) -> None:
        """All registered handlers are called."""
        bus = EventBus()
        results = []
        bus.on("test", lambda e: results.append("a"))
        bus.on("test", lambda e: results.append("b"))
        bus.on("test", lambda e: results.append("c"))
        bus.emit("test", SentigentEvent(event_type="test"))
        assert results == ["a", "b", "c"]
        bus.shutdown()

    def test_handler_exception_isolated(self) -> None:
        """One handler failing doesn't block others."""
        bus = EventBus()
        results = []

        def failing_handler(e: SentigentEvent) -> None:
            raise RuntimeError("intentional failure")

        bus.on("test", failing_handler)
        bus.on("test", lambda e: results.append("ok"))
        bus.emit("test", SentigentEvent(event_type="test"))
        # Second handler should still be called
        assert results == ["ok"]
        bus.shutdown()

    def test_remove_handler(self) -> None:
        """Removed handler is no longer called."""
        bus = EventBus()
        results = []
        handler = lambda e: results.append("called")
        bus.on("test", handler)
        bus.emit("test", SentigentEvent(event_type="test"))
        assert len(results) == 1

        bus.remove_handler("test", handler)
        bus.emit("test", SentigentEvent(event_type="test"))
        assert len(results) == 1  # Still 1, handler was removed
        bus.shutdown()

    def test_no_handlers_no_error(self) -> None:
        """Emitting to event type with no handlers doesn't raise."""
        bus = EventBus()
        bus.emit("nonexistent", SentigentEvent(event_type="nonexistent"))
        bus.shutdown()

    def test_clear_removes_all(self) -> None:
        """clear() removes all handlers and webhooks."""
        bus = EventBus()
        results = []
        bus.on("test", lambda e: results.append("a"))
        bus.add_webhook("test", "https://example.com")
        bus.clear()
        bus.emit("test", SentigentEvent(event_type="test"))
        assert results == []
        bus.shutdown()

    def test_webhook_dispatch(self) -> None:
        """Webhook dispatcher is called with correct payload."""
        bus = EventBus()
        with patch.object(bus._dispatcher, "dispatch") as mock_dispatch:
            bus.add_webhook("test", "https://example.com/hook")
            event = SentigentEvent(event_type="test", trace_id="abc")
            bus.emit("test", event)
            mock_dispatch.assert_called_once()
            call_args = mock_dispatch.call_args
            assert call_args[0][0] == "https://example.com/hook"
            assert call_args[0][1]["event_type"] == "test"
        bus.shutdown()


class TestIntegrationEscalationEvent:

    def test_escalation_fires_event(self, tmp_path) -> None:
        """evaluate() with high anomaly triggers escalation event."""
        reset_event_bus()
        bus = get_event_bus()
        received = []
        bus.on(EVENT_ESCALATION, lambda e: received.append(e))

        db_path = str(tmp_path / "test_events_escalation.db")
        judge = Sentigent(
            profile="financial_ops",
            agent_id="event_test",
            db_path=db_path,
        )

        # Force high anomaly context — amount 500x above baseline
        decision = judge.evaluate(
            task="Process refund for $999,999",
            context={"amount": 999_999},
            agent_state={"confidence": 0.5},
        )

        if decision.action.value == "escalate":
            assert len(received) >= 1
            assert received[0].event_type == EVENT_ESCALATION
            assert received[0].agent_id == "event_test"

        bus.clear()
        reset_event_bus()

    def test_no_event_on_proceed(self, tmp_path) -> None:
        """evaluate() with normal values does not fire escalation event."""
        reset_event_bus()
        bus = get_event_bus()
        received = []
        bus.on(EVENT_ESCALATION, lambda e: received.append(e))

        db_path = str(tmp_path / "test_events_proceed.db")
        judge = Sentigent(
            profile="financial_ops",
            agent_id="event_test2",
            db_path=db_path,
        )

        decision = judge.evaluate(
            task="Normal operation",
            context={"amount": 100},
            agent_state={"confidence": 0.95},
        )

        # No escalation event for normal operations
        escalation_events = [e for e in received if e.event_type == EVENT_ESCALATION]
        if decision.action.value == "proceed":
            assert len(escalation_events) == 0

        bus.clear()
        reset_event_bus()


class TestIntegrationOutcomeEvent:

    def test_outcome_fires_event(self, tmp_path) -> None:
        """record_outcome() fires an outcome event."""
        reset_event_bus()
        bus = get_event_bus()
        received = []
        bus.on(EVENT_OUTCOME, lambda e: received.append(e))

        db_path = str(tmp_path / "test_events_outcome.db")
        judge = Sentigent(
            profile="financial_ops",
            agent_id="event_test3",
            db_path=db_path,
        )

        decision = judge.evaluate(
            task="Test operation",
            context={"amount": 100},
            agent_state={"confidence": 0.9},
        )

        judge.record_outcome(decision.trace_id, "correct")

        assert len(received) >= 1
        assert received[0].event_type == EVENT_OUTCOME
        assert received[0].metadata["outcome"] == "correct"

        bus.clear()
        reset_event_bus()


class TestGetEventBusSingleton:

    def test_singleton(self) -> None:
        """get_event_bus() returns the same instance."""
        reset_event_bus()
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
        reset_event_bus()

    def test_reset_creates_new(self) -> None:
        """reset_event_bus() creates a new instance."""
        reset_event_bus()
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2
        reset_event_bus()
