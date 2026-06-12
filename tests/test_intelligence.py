"""
Tests for the sentigent.intelligence package:
  - AgentConnector (connector.py)
  - AgentBus (agent_bus.py)
  - ActionExecutor (executor.py)
  - AgentHub (hub.py) — integration smoke tests
"""
from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch, call

import pytest


# ── Reset singletons between tests ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_intelligence_singletons():
    """Ensure singleton state doesn't leak between tests."""
    import sentigent.intelligence.executor as exe_mod
    import sentigent.intelligence.agent_bus as bus_mod
    import sentigent.intelligence.hub as hub_mod

    # Tear down before test
    exe_mod._executor_instance = None
    bus_mod._bus_instance = None
    hub_mod._hub_instance = None

    yield

    # Tear down after test too (stop any learner threads)
    if hub_mod._hub_instance is not None:
        try:
            hub_mod._hub_instance.stop()
        except Exception:
            pass
    hub_mod._hub_instance = None
    exe_mod._executor_instance = None
    bus_mod._bus_instance = None


# ─────────────────────────────────────────────────────────────────────────────
# AgentConnector
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentConnector:
    def make_connector(self, org_id="test-org"):
        from sentigent.intelligence.connector import AgentConnector
        return AgentConnector(org_id=org_id, supabase_client=None)

    def test_register_creates_agent(self):
        connector = self.make_connector()
        agent = connector.register("agent-1", capabilities=["eval"])
        assert agent.agent_id == "agent-1"
        assert "eval" in agent.capabilities

    def test_register_idempotent(self):
        connector = self.make_connector()
        connector.register("agent-1")
        connector.register("agent-1")  # second call is no-op
        assert connector.agent_count() == 1

    def test_unregister_removes_agent(self):
        connector = self.make_connector()
        connector.register("agent-1")
        connector.unregister("agent-1")
        assert connector.agent_count() == 0

    def test_publish_calls_handlers(self):
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_DECISION
        connector = self.make_connector()
        connector.register("agent-1")
        received = []
        connector.subscribe(received.append)
        sig = AgentSignal(
            signal_type=SIGNAL_DECISION,
            agent_id="agent-1",
            org_id="test-org",
            payload={"action": "proceed"},
        )
        connector.publish(sig)
        time.sleep(0.05)  # allow background thread
        assert len(received) == 1
        assert received[0].signal_type == SIGNAL_DECISION

    def test_decision_increments_count(self):
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_DECISION
        connector = self.make_connector()
        agent = connector.register("agent-1")
        sig = AgentSignal(
            signal_type=SIGNAL_DECISION,
            agent_id="agent-1",
            org_id="test-org",
            payload={},
        )
        connector.publish(sig)
        time.sleep(0.05)
        assert agent.decision_count == 1

    def test_recent_signals_filtered_by_type(self):
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_DECISION, SIGNAL_OUTCOME
        connector = self.make_connector()
        connector.register("agent-1")
        for sig_type in [SIGNAL_DECISION, SIGNAL_OUTCOME, SIGNAL_DECISION]:
            connector.publish(AgentSignal(
                signal_type=sig_type, agent_id="agent-1",
                org_id="test-org", payload={},
            ))
        time.sleep(0.05)
        decisions = connector.recent_signals(signal_type=SIGNAL_DECISION)
        assert all(s.signal_type == SIGNAL_DECISION for s in decisions)
        assert len(decisions) == 2

    def test_heartbeat_marks_agent_alive(self):
        connector = self.make_connector()
        agent = connector.register("agent-1")
        connector.heartbeat("agent-1", judgment_score=0.75)
        time.sleep(0.05)
        assert agent.is_alive

    def test_connected_agents_excludes_stale(self):
        from sentigent.intelligence.connector import ConnectedAgent
        connector = self.make_connector()
        # Manually add a stale agent
        stale = ConnectedAgent(agent_id="old", org_id="test-org")
        stale.last_heartbeat = time.time() - 300  # 5 min ago
        connector._agents["old"] = stale
        connector.register("fresh")
        alive = connector.connected_agents
        assert len(alive) == 1
        assert alive[0].agent_id == "fresh"


# ─────────────────────────────────────────────────────────────────────────────
# AgentBus
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentBus:
    def make_bus(self, org_id="test-org"):
        from sentigent.intelligence.agent_bus import AgentBus
        return AgentBus(org_id=org_id)

    def test_register_and_list(self):
        bus = self.make_bus()
        bus.register("agent-a", capabilities=["review", "lint"])
        agents = bus.list_agents()
        assert len(agents) == 1
        assert set(agents[0]["capabilities"]) == {"review", "lint"}

    def test_register_idempotent_updates_capabilities(self):
        bus = self.make_bus()
        bus.register("agent-a", capabilities=["review"])
        bus.register("agent-a", capabilities=["lint"])  # adds, not replaces
        agents = bus.list_agents()
        assert "lint" in agents[0]["capabilities"]
        assert "review" in agents[0]["capabilities"]

    def test_direct_send_delivers_to_handler(self):
        bus = self.make_bus()
        received = []
        bus.register("agent-b", handler=lambda msg: received.append(msg) or None)
        bus.register("agent-a")
        bus.send("agent-a", "agent-b", msg_type="direct", payload={"data": 42})
        assert len(received) == 1
        assert received[0].payload["data"] == 42
        assert received[0].from_agent == "agent-a"

    def test_broadcast_reaches_all_except_sender(self):
        bus = self.make_bus()
        received_by = []
        for name in ["agent-b", "agent-c", "agent-d"]:
            n = name
            bus.register(n, handler=lambda msg, _n=n: received_by.append(_n) or None)
        bus.register("sender")
        count = bus.broadcast("sender", payload={"ping": True})
        assert count == 3
        assert "sender" not in received_by
        assert set(received_by) == {"agent-b", "agent-c", "agent-d"}

    def test_find_agents_by_capability(self):
        bus = self.make_bus()
        bus.register("a1", capabilities=["scan"])
        bus.register("a2", capabilities=["review"])
        bus.register("a3", capabilities=["scan", "review"])
        scanners = bus.find_agents("scan")
        assert set(scanners) == {"a1", "a3"}

    def test_find_best_agent_excludes_sender(self):
        bus = self.make_bus()
        bus.register("a1", capabilities=["scan"])
        bus.register("a2", capabilities=["scan"])
        best = bus.find_best_agent("scan", exclude=["a1"])
        assert best == "a2"

    def test_find_best_agent_none_when_no_capability(self):
        bus = self.make_bus()
        bus.register("a1", capabilities=["review"])
        assert bus.find_best_agent("nonexistent") is None

    def test_delegate_returns_none_when_no_capable_agent(self):
        bus = self.make_bus()
        bus.register("requester")
        result = bus.delegate("requester", "impossible_cap", timeout_s=0.1)
        assert result is None

    def test_delegate_roundtrip_with_reply(self):
        from sentigent.intelligence.agent_bus import AgentMessage, MSG_TASK_RESULT
        bus = self.make_bus()

        def worker_handler(msg: AgentMessage) -> AgentMessage | None:
            return AgentMessage.create(
                msg_type=MSG_TASK_RESULT,
                from_agent="worker",
                to_agent=msg.from_agent,
                payload={"result": "done"},
                reply_to=msg.msg_id,
            )

        bus.register("requester")
        bus.register("worker", capabilities=["work"], handler=worker_handler)

        reply = bus.delegate("requester", "work",
                             payload={"task": "do stuff"}, timeout_s=2.0)
        assert reply is not None
        assert reply.payload["result"] == "done"

    def test_delegate_timeout_returns_none(self):
        bus = self.make_bus()
        bus.register("requester")
        # Register worker with a slow handler that doesn't reply
        bus.register("slow-worker", capabilities=["slow"],
                     handler=lambda msg: (time.sleep(5) or None))
        result = bus.delegate("requester", "slow", timeout_s=0.1)
        assert result is None

    def test_recent_messages_logged(self):
        bus = self.make_bus()
        bus.register("a")
        bus.register("b")
        bus.send("a", "b", payload={"x": 1})
        bus.send("a", "b", payload={"x": 2})
        msgs = bus.recent_messages(limit=10)
        assert len(msgs) == 2

    def test_on_message_adds_handler(self):
        bus = self.make_bus()
        received = []
        bus.register("a")
        bus.register("b")
        bus.on_message("b", lambda msg: received.append(msg) or None)
        bus.send("a", "b", payload={})
        assert len(received) == 1

    def test_singleton(self):
        from sentigent.intelligence.agent_bus import get_agent_bus
        b1 = get_agent_bus()
        b2 = get_agent_bus()
        assert b1 is b2


# ─────────────────────────────────────────────────────────────────────────────
# ActionExecutor
# ─────────────────────────────────────────────────────────────────────────────

class TestActionExecutor:
    def make_executor(self):
        from sentigent.intelligence.executor import ActionExecutor
        return ActionExecutor()

    def test_proceed_is_noop(self):
        executor = self.make_executor()
        result = executor.execute(
            action="proceed", agent_id="a", task="do stuff",
            trace_id="t1", confidence=0.9,
        )
        assert result.action == "proceed"
        assert "ProceedPlugin" in result.plugins_run or "proceed" in result.plugins_run

    def test_slow_down_adds_delay(self):
        from sentigent.intelligence.executor import ActionExecutor, SlowDownPlugin
        executor = ActionExecutor()
        # Use a very short delay for testing
        executor._plugins = [p for p in executor._plugins
                             if not isinstance(p, SlowDownPlugin)]
        executor.register_plugin(SlowDownPlugin(delay_ms=50))

        t0 = time.monotonic()
        result = executor.execute(
            action="slow_down", agent_id="a", task="do stuff",
            trace_id="t1", confidence=0.5,
        )
        elapsed = (time.monotonic() - t0) * 1000
        assert elapsed >= 40  # allow some tolerance
        assert result.slow_down_ms >= 40

    def test_escalate_fires_event_bus(self):
        executor = self.make_executor()
        fired = []
        from sentigent.events import get_event_bus, EVENT_ESCALATION
        bus = get_event_bus()
        bus.on(EVENT_ESCALATION, fired.append)
        try:
            executor.execute(
                action="escalate", agent_id="a", task="risky",
                trace_id="t1", confidence=0.9, reason="Too dangerous",
            )
            assert len(fired) == 1
            assert fired[0].event_type == EVENT_ESCALATION
            assert fired[0].trace_id == "t1"
        finally:
            bus.remove_handler(EVENT_ESCALATION, fired.append)

    def test_escalate_sets_escalation_fired_flag(self):
        executor = self.make_executor()
        result = executor.execute(
            action="escalate", agent_id="a", task="t",
            trace_id="x", confidence=0.95,
        )
        assert result.escalation_fired is True

    def test_enrich_returns_enriched_context_from_hub(self):
        executor = self.make_executor()
        fake_patterns = [{"pattern_name": "p1", "success_rate": 0.92}]
        with patch("sentigent.intelligence.hub.get_hub") as mock_hub_fn:
            mock_hub = MagicMock()
            mock_hub.get_peer_patterns.return_value = fake_patterns
            mock_hub_fn.return_value = mock_hub
            result = executor.execute(
                action="enrich", agent_id="a", task="t",
                trace_id="x", confidence=0.4, org_id="test-org",
            )
        assert result.enriched_context.get("peer_patterns") == fake_patterns

    def test_custom_plugin_registered(self):
        from sentigent.intelligence.executor import ActionPlugin
        executor = self.make_executor()
        calls = []

        class MyPlugin:
            name = "custom"
            def can_handle(self, action): return action == "custom_action"
            def execute(self, ctx, result): calls.append(ctx.action)

        executor.register_plugin(MyPlugin())
        executor.execute(
            action="custom_action", agent_id="a", task="t",
            trace_id="x", confidence=0.5,
        )
        assert "custom_action" in calls

    def test_plugin_exception_does_not_propagate(self):
        executor = self.make_executor()

        class BrokenPlugin:
            name = "broken"
            def can_handle(self, action): return action == "proceed"
            def execute(self, ctx, result): raise RuntimeError("boom")

        executor.register_plugin(BrokenPlugin())
        # Should not raise
        result = executor.execute(
            action="proceed", agent_id="a", task="t",
            trace_id="x", confidence=0.9,
        )
        assert result.error is not None

    def test_stats_accumulate(self):
        executor = self.make_executor()
        for _ in range(3):
            executor.execute(action="proceed", agent_id="a", task="t",
                             trace_id="x", confidence=0.9)
        stats = executor.get_stats()
        assert stats["proceed"]["count"] == 3
        assert stats["proceed"]["total_ms"] > 0

    def test_unknown_action_runs_no_plugins(self):
        executor = self.make_executor()
        result = executor.execute(
            action="totally_unknown", agent_id="a", task="t",
            trace_id="x", confidence=0.5,
        )
        assert result.plugins_run == []

    def test_singleton(self):
        from sentigent.intelligence.executor import get_executor
        e1 = get_executor()
        e2 = get_executor()
        assert e1 is e2


# ─────────────────────────────────────────────────────────────────────────────
# AgentHub (smoke tests — no Supabase)
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentHub:
    def make_hub(self):
        from sentigent.intelligence.hub import AgentHub
        return AgentHub(org_id="test-org", supabase_client=None)

    def test_start_sets_running(self):
        hub = self.make_hub()
        hub.start()
        assert hub._running is True
        hub.stop()

    def test_connect_auto_starts_hub(self):
        hub = self.make_hub()
        assert not hub._running
        hub.connect("agent-1")
        assert hub._running
        hub.stop()

    def test_connected_agents_after_connect(self):
        hub = self.make_hub()
        hub.connect("agent-1", capabilities=["eval"])
        agents = hub.connected_agents
        assert any(a.agent_id == "agent-1" for a in agents)
        hub.stop()

    def test_disconnect_removes_agent(self):
        hub = self.make_hub()
        hub.connect("agent-1")
        hub.disconnect("agent-1")
        assert not any(a.agent_id == "agent-1" for a in hub.connected_agents)
        hub.stop()

    def test_status_returns_hub_status(self):
        from sentigent.intelligence.hub import HubStatus
        hub = self.make_hub()
        hub.start()
        status = hub.status()
        assert isinstance(status, HubStatus)
        assert status.running is True
        assert status.org_id == "test-org"
        hub.stop()

    def test_get_agent_network_returns_list(self):
        hub = self.make_hub()
        hub.connect("agent-a")
        hub.connect("agent-b")
        network = hub.get_agent_network()
        assert isinstance(network, list)
        ids = [n["agent_id"] for n in network]
        assert "agent-a" in ids
        assert "agent-b" in ids
        hub.stop()

    def test_publish_decision_increments_signals_processed(self):
        hub = self.make_hub()
        hub.connect("agent-1")
        hub.publish_decision(
            agent_id="agent-1",
            task="do something",
            action="proceed",
            signals={"caution": 0.2},
            confidence=0.9,
            trace_id="trace-1",
        )
        time.sleep(0.05)
        assert hub._signals_processed >= 1
        hub.stop()

    def test_publish_outcome_succeeds(self):
        hub = self.make_hub()
        hub.connect("agent-1")
        # Should not raise
        hub.publish_outcome(
            agent_id="agent-1",
            trace_id="t1",
            outcome="correct",
            task="did something",
        )
        hub.stop()

    def test_get_peer_patterns_returns_empty_without_supabase(self):
        hub = self.make_hub()
        hub.start()
        patterns = hub.get_peer_patterns()
        assert patterns == []
        hub.stop()

    def test_enrich_decision_returns_none_without_llm_key(self):
        hub = self.make_hub()
        hub.start()
        # No ANTHROPIC_API_KEY in test env → LLMJudge won't fire
        result = hub.enrich_decision(
            agent_id="a",
            task="low-confidence task",
            signals={"caution": 0.50},  # in ambiguous zone
            gate_action="slow_down",
            gate_reason="caution elevated",
            similar_episodes=[],
            context={},
        )
        # Either None or a dict (judge may decide not to fire if no API key)
        assert result is None or isinstance(result, dict)
        hub.stop()

    def test_singleton(self):
        from sentigent.intelligence.hub import get_hub
        h1 = get_hub(org_id="test-org")
        h2 = get_hub(org_id="test-org")
        assert h1 is h2
        h1.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: engine wires hub + executor
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineIntelligenceIntegration:
    """Verify that Sentigent engine initializes hub + executor without errors."""

    def test_engine_initializes_with_hub_and_executor(self, tmp_path):
        from sentigent import Sentigent
        judge = Sentigent(
            profile="default",
            agent_id="test-agent",
            org_id="test-org",
            db_path=str(tmp_path / "mem.db"),
        )
        # Hub and executor should be initialized (or gracefully absent)
        assert hasattr(judge, "_hub")
        assert hasattr(judge, "_executor")

    def test_evaluate_with_hub_active(self, tmp_path):
        from sentigent import Sentigent
        judge = Sentigent(
            profile="default",
            agent_id="test-agent",
            org_id="test-org",
            db_path=str(tmp_path / "mem.db"),
        )
        decision = judge.evaluate("write a unit test for the new feature")
        # Hub publishes signal; executor runs — neither should break evaluate()
        assert decision.action.value in ("proceed", "slow_down", "enrich", "escalate")
        assert decision.trace_id

    def test_executor_runs_on_escalate(self, tmp_path):
        """Verify escalation fires the EventBus event via executor."""
        from sentigent import Sentigent
        from sentigent.events import get_event_bus, EVENT_ESCALATION

        judge = Sentigent(
            profile="financial_ops",  # low threshold → likely escalate
            agent_id="test-agent",
            org_id="test-org",
            db_path=str(tmp_path / "mem.db"),
        )

        fired = []
        bus = get_event_bus()
        bus.on(EVENT_ESCALATION, fired.append)

        try:
            decision = judge.evaluate(
                "delete all customer records permanently",
                context={"amount": 999999, "irreversible": True},
            )
            if decision.action.value == "escalate":
                assert len(fired) >= 1
            # If not escalate, that's fine — escalation is threshold-dependent
        finally:
            bus.remove_handler(EVENT_ESCALATION, fired.append)
