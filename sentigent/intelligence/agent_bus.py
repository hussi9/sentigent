"""
AgentBus — inter-agent messaging and capability routing.

Sits above AgentConnector to add:
  1. Direct agent-to-agent messaging (targeted, not hub broadcast)
  2. Capability-based routing (find the right agent for a task)
  3. Task delegation with timeout (agent A → agent B, wait for reply)
  4. Org-wide broadcast (e.g., "pattern discovered, re-pull rules")

Architecture:

  Agent A ──► AgentBus.send(to="agent-B", ...) ──► Agent B's handler
                     │
                     ▼
             AgentConnector (SIGNAL_MESSAGE) ──► Supabase / hub log

All messaging is in-process (sub-millisecond). Cross-process routing
via Supabase Realtime is planned as a future extension.

Usage:
    from sentigent.intelligence.agent_bus import get_agent_bus

    bus = get_agent_bus()

    # Register this agent and its capabilities
    bus.register("code-reviewer", capabilities=["review", "lint"])

    # Listen for direct messages
    bus.on_message("code-reviewer", my_message_handler)

    # Send a direct message
    bus.send("code-reviewer", "security-scanner",
             msg_type="task_delegate",
             payload={"task": "scan for SQL injection"})

    # Route to best agent with a capability
    result = bus.delegate("security-scanner", "review",
                          payload={"code": "..."}, timeout_s=5.0)
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Message Types ─────────────────────────────────────────────────────────────

MSG_DIRECT           = "direct"           # targeted message to one agent
MSG_TASK_DELEGATE    = "task_delegate"    # delegate a subtask to another agent
MSG_TASK_RESULT      = "task_result"      # reply to a task delegation
MSG_CAPABILITY_REQ   = "capability_req"   # "who can handle X?"
MSG_CAPABILITY_RESP  = "capability_resp"  # "I can handle X"
MSG_BROADCAST        = "broadcast"        # org-wide announcement

ALL_MSG_TYPES = (
    MSG_DIRECT, MSG_TASK_DELEGATE, MSG_TASK_RESULT,
    MSG_CAPABILITY_REQ, MSG_CAPABILITY_RESP, MSG_BROADCAST,
)


# ─────────────────────────────────────────────────────────────────────────────
# Message model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentMessage:
    """A routed message between agents on the bus."""
    msg_id: str
    msg_type: str
    from_agent: str
    to_agent: str | None      # None = broadcast
    payload: dict[str, Any]
    reply_to: str | None = None     # msg_id this is a reply to
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        msg_type: str,
        from_agent: str,
        to_agent: str | None,
        payload: dict[str, Any],
        reply_to: str | None = None,
    ) -> "AgentMessage":
        return cls(
            msg_id=str(uuid.uuid4()),
            msg_type=msg_type,
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload,
            reply_to=reply_to,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registered agent
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BusAgent:
    agent_id: str
    capabilities: set[str]
    handlers: list[Callable[[AgentMessage], AgentMessage | None]]
    inbox: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=200))
    registered_at: float = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# AgentBus
# ─────────────────────────────────────────────────────────────────────────────

class AgentBus:
    """
    Central message router for all agents in the org.

    Thread-safe. All routing is in-memory (sub-ms). Designed to add
    cross-process routing on top without API changes.
    """

    def __init__(self, org_id: str = "") -> None:
        self._org_id = org_id
        self._agents: dict[str, BusAgent] = {}
        self._lock = threading.RLock()
        # Pending replies: msg_id → reply queue (for request/reply)
        self._pending: dict[str, queue.Queue] = {}
        # Message log (rolling 500)
        self._log: list[AgentMessage] = []

    # ──────────────────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────────────────

    def register(
        self,
        agent_id: str,
        capabilities: list[str] | None = None,
        handler: Callable[[AgentMessage], AgentMessage | None] | None = None,
    ) -> None:
        """
        Register an agent on the bus.

        Args:
            agent_id: Unique agent identifier
            capabilities: List of capability strings (e.g. ["review", "lint"])
            handler: Optional message handler. Receives AgentMessage, may return
                     a reply AgentMessage (or None for fire-and-forget).
        """
        with self._lock:
            if agent_id not in self._agents:
                self._agents[agent_id] = BusAgent(
                    agent_id=agent_id,
                    capabilities=set(capabilities or []),
                    handlers=[],
                )
                logger.debug("AgentBus: registered %s caps=%s", agent_id, capabilities)
            else:
                # Update capabilities
                self._agents[agent_id].capabilities.update(capabilities or [])

            if handler:
                self._agents[agent_id].handlers.append(handler)

        # Publish registration to connector/hub (non-blocking)
        self._publish_to_hub(agent_id, "registered", {"capabilities": capabilities or []})

    def unregister(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
        logger.debug("AgentBus: unregistered %s", agent_id)

    def on_message(
        self,
        agent_id: str,
        handler: Callable[[AgentMessage], AgentMessage | None],
    ) -> None:
        """Register a message handler for an already-registered agent."""
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].handlers.append(handler)

    # ──────────────────────────────────────────────────────────────────────
    # Sending
    # ──────────────────────────────────────────────────────────────────────

    def send(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str = MSG_DIRECT,
        payload: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> str:
        """
        Send a direct message to a specific agent.

        Returns the msg_id (for request/reply correlation).
        Delivery is synchronous in-process; handlers called inline.
        """
        msg = AgentMessage.create(
            msg_type=msg_type,
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload or {},
            reply_to=reply_to,
        )
        self._deliver(msg)
        return msg.msg_id

    def broadcast(
        self,
        from_agent: str,
        msg_type: str = MSG_BROADCAST,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """
        Broadcast a message to all registered agents.

        Returns count of agents that received the message.
        """
        msg = AgentMessage.create(
            msg_type=msg_type,
            from_agent=from_agent,
            to_agent=None,
            payload=payload or {},
        )
        with self._lock:
            targets = [aid for aid in self._agents if aid != from_agent]

        count = 0
        for target in targets:
            targeted_msg = AgentMessage(
                msg_id=msg.msg_id,
                msg_type=msg.msg_type,
                from_agent=msg.from_agent,
                to_agent=target,
                payload=msg.payload,
                timestamp=msg.timestamp,
            )
            self._deliver(targeted_msg)
            count += 1

        logger.debug("AgentBus: broadcast from=%s to %d agents", from_agent, count)
        return count

    def delegate(
        self,
        from_agent: str,
        required_capability: str,
        payload: dict[str, Any] | None = None,
        timeout_s: float = 5.0,
        exclude: list[str] | None = None,
    ) -> AgentMessage | None:
        """
        Delegate a task to the best available agent with `required_capability`.

        Blocks until reply received or timeout.

        Args:
            from_agent: Delegating agent's ID
            required_capability: Capability required (e.g., "review")
            payload: Task payload
            timeout_s: Max wait time for reply
            exclude: Agent IDs to skip

        Returns:
            Reply AgentMessage, or None on timeout/no-agent.
        """
        target = self.find_best_agent(required_capability, exclude=[from_agent] + (exclude or []))
        if target is None:
            logger.debug(
                "AgentBus: no agent with capability=%s for delegation from=%s",
                required_capability, from_agent,
            )
            return None

        reply_queue: queue.Queue = queue.Queue(maxsize=1)
        msg = AgentMessage.create(
            msg_type=MSG_TASK_DELEGATE,
            from_agent=from_agent,
            to_agent=target,
            payload={"capability": required_capability, **(payload or {})},
        )

        with self._lock:
            self._pending[msg.msg_id] = reply_queue

        self._deliver(msg)

        try:
            reply = reply_queue.get(timeout=timeout_s)
            return reply
        except queue.Empty:
            logger.debug(
                "AgentBus: delegation timeout after %.1fs from=%s to=%s cap=%s",
                timeout_s, from_agent, target, required_capability,
            )
            return None
        finally:
            with self._lock:
                self._pending.pop(msg.msg_id, None)

    # ──────────────────────────────────────────────────────────────────────
    # Capability routing
    # ──────────────────────────────────────────────────────────────────────

    def find_agents(self, capability: str) -> list[str]:
        """Return all agent IDs that have the given capability."""
        with self._lock:
            return [
                aid for aid, agent in self._agents.items()
                if capability in agent.capabilities
            ]

    def find_best_agent(
        self,
        capability: str,
        exclude: list[str] | None = None,
    ) -> str | None:
        """
        Return the best agent with the given capability.

        "Best" currently means: registered (alive). Future: add
        judgment_score, queue depth, and specialization matching.
        """
        exclude_set = set(exclude or [])
        candidates = [
            aid for aid, agent in self._agents.items()
            if capability in agent.capabilities and aid not in exclude_set
        ]
        return candidates[0] if candidates else None

    # ──────────────────────────────────────────────────────────────────────
    # Introspection
    # ──────────────────────────────────────────────────────────────────────

    def list_agents(self) -> list[dict[str, Any]]:
        """Return all registered agents with their capabilities."""
        with self._lock:
            return [
                {
                    "agent_id": aid,
                    "capabilities": sorted(agent.capabilities),
                    "registered_at": agent.registered_at,
                    "handler_count": len(agent.handlers),
                }
                for aid, agent in self._agents.items()
            ]

    def recent_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent messages on the bus."""
        with self._lock:
            msgs = list(reversed(self._log))[:limit]
        return [
            {
                "msg_id": m.msg_id,
                "msg_type": m.msg_type,
                "from_agent": m.from_agent,
                "to_agent": m.to_agent,
                "payload_keys": list(m.payload.keys()),
                "timestamp": m.timestamp,
            }
            for m in msgs
        ]

    # ──────────────────────────────────────────────────────────────────────
    # Internal delivery
    # ──────────────────────────────────────────────────────────────────────

    def _deliver(self, msg: AgentMessage) -> None:
        """Deliver a message to the target agent's handlers. Sync."""
        # Log the message (rolling)
        with self._lock:
            self._log.append(msg)
            if len(self._log) > 500:
                self._log = self._log[-500:]

        to = msg.to_agent
        if to is None:
            return  # broadcast already expanded by caller

        with self._lock:
            agent = self._agents.get(to)
            handlers = list(agent.handlers) if agent else []
            reply_queue = self._pending.get(msg.reply_to) if msg.reply_to else None

        # Deliver to pending reply waiter first
        if reply_queue is not None:
            try:
                reply_queue.put_nowait(msg)
            except queue.Full:
                pass

        # Call registered handlers
        for handler in handlers:
            try:
                reply = handler(msg)
                if reply is not None and isinstance(reply, AgentMessage):
                    # Auto-route the reply back
                    threading.Thread(
                        target=self._deliver, args=(reply,), daemon=True
                    ).start()
            except Exception as exc:
                logger.debug(
                    "AgentBus handler error agent=%s msg_type=%s: %s",
                    to, msg.msg_type, exc,
                )

    def _publish_to_hub(
        self, agent_id: str, event: str, payload: dict[str, Any]
    ) -> None:
        """Optionally forward bus events to hub connector for Supabase logging."""
        try:
            from sentigent.intelligence.hub import get_hub
            hub = get_hub(org_id=self._org_id)
            if hub._connector:
                from sentigent.intelligence.connector import AgentSignal
                hub._connector.publish(AgentSignal(
                    signal_type="bus_event",
                    agent_id=agent_id,
                    org_id=self._org_id,
                    payload={"event": event, **payload},
                ))
        except Exception:
            pass  # hub not available — that's fine


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_bus_lock = threading.Lock()
_bus_instance: AgentBus | None = None


def get_agent_bus(org_id: str = "") -> AgentBus:
    """Return the singleton AgentBus for this process."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance is None:
            import os
            resolved = org_id or os.environ.get("SENTIGENT_ORG_ID", "")
            _bus_instance = AgentBus(org_id=resolved)
        return _bus_instance
