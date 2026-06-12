"""
AgentConnector — agent registration and real-time signal protocol.

Every agent that connects to the hub:
  1. Registers with its agent_id, org_id, capabilities
  2. Gets a Supabase Realtime channel subscription
  3. Publishes signals (decisions, prompts, outcomes) to the org channel
  4. Receives patterns + insights from the hub

Signal types published to the org channel:
  DECISION   — agent made a decision (action + signals + task)
  OUTCOME    — decision outcome recorded (correct/incorrect)
  PROMPT     — prompt sent to underlying LLM (quality metadata)
  HEARTBEAT  — agent alive + current judgment score
  PATTERN    — new pattern learned (broadcast to all peers)

All signals are scoped to org_id — no cross-org leakage.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

SIGNAL_DECISION  = "decision"
SIGNAL_OUTCOME   = "outcome"
SIGNAL_PROMPT    = "prompt"
SIGNAL_HEARTBEAT = "heartbeat"
SIGNAL_PATTERN   = "pattern"


@dataclass
class AgentSignal:
    signal_type: str
    agent_id: str
    org_id: str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConnectedAgent:
    agent_id: str
    org_id: str
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    judgment_score: float = 0.0
    decision_count: int = 0
    capabilities: list[str] = field(default_factory=list)

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < 120  # 2 min timeout


class AgentConnector:
    """
    Manages agent registration and signal routing.

    In-process: uses a shared signal queue (no network needed for same process).
    Cross-process: publishes to Supabase `agent_signals` table + Realtime.
    """

    def __init__(self, org_id: str, supabase_client: Any = None) -> None:
        self._org_id = org_id
        self._supabase = supabase_client
        self._agents: dict[str, ConnectedAgent] = {}
        self._signal_handlers: list[Callable[[AgentSignal], None]] = []
        self._lock = threading.Lock()
        # In-memory queue for same-process signal passing
        self._signal_queue: list[AgentSignal] = []

    # ──────────────────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────────────────

    def register(
        self,
        agent_id: str,
        capabilities: list[str] | None = None,
    ) -> ConnectedAgent:
        """Register an agent with the hub. Idempotent."""
        with self._lock:
            if agent_id not in self._agents:
                agent = ConnectedAgent(
                    agent_id=agent_id,
                    org_id=self._org_id,
                    capabilities=capabilities or [],
                )
                self._agents[agent_id] = agent
                logger.info("Agent registered: %s (org=%s)", agent_id, self._org_id)

                # Persist to Layer 2
                self._persist_registration(agent)
            else:
                self._agents[agent_id].last_heartbeat = time.time()

            return self._agents[agent_id]

    def unregister(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
            logger.info("Agent disconnected: %s", agent_id)

    @property
    def connected_agents(self) -> list[ConnectedAgent]:
        with self._lock:
            return [a for a in self._agents.values() if a.is_alive]

    def agent_count(self) -> int:
        return len(self.connected_agents)

    # ──────────────────────────────────────────────────────────────────────
    # Signal publishing
    # ──────────────────────────────────────────────────────────────────────

    def publish(self, signal: AgentSignal) -> None:
        """Publish a signal to all subscribers + Layer 2."""
        # Update agent state from signal
        with self._lock:
            agent = self._agents.get(signal.agent_id)
            if agent:
                agent.last_heartbeat = time.time()
                if signal.signal_type == SIGNAL_DECISION:
                    agent.decision_count += 1
                if signal.signal_type == SIGNAL_HEARTBEAT:
                    agent.judgment_score = signal.payload.get("judgment_score", 0.0)

            # Enqueue for in-process subscribers
            self._signal_queue.append(signal)
            if len(self._signal_queue) > 500:
                self._signal_queue = self._signal_queue[-500:]

        # Notify handlers
        for handler in self._signal_handlers:
            try:
                handler(signal)
            except Exception as exc:
                logger.debug("Signal handler error: %s", exc)

        # Async persist to Layer 2 (non-blocking)
        threading.Thread(
            target=self._persist_signal, args=(signal,), daemon=True
        ).start()

    def subscribe(self, handler: Callable[[AgentSignal], None]) -> None:
        """Subscribe to all signals from all connected agents."""
        self._signal_handlers.append(handler)

    def recent_signals(
        self,
        agent_id: str | None = None,
        signal_type: str | None = None,
        limit: int = 50,
    ) -> list[AgentSignal]:
        """Get recent in-memory signals."""
        with self._lock:
            signals = list(reversed(self._signal_queue))
        if agent_id:
            signals = [s for s in signals if s.agent_id == agent_id]
        if signal_type:
            signals = [s for s in signals if s.signal_type == signal_type]
        return signals[:limit]

    # ──────────────────────────────────────────────────────────────────────
    # Heartbeat
    # ──────────────────────────────────────────────────────────────────────

    def heartbeat(self, agent_id: str, judgment_score: float = 0.0) -> None:
        self.publish(AgentSignal(
            signal_type=SIGNAL_HEARTBEAT,
            agent_id=agent_id,
            org_id=self._org_id,
            payload={"judgment_score": judgment_score},
        ))

    # ──────────────────────────────────────────────────────────────────────
    # Supabase persistence
    # ──────────────────────────────────────────────────────────────────────

    def _persist_registration(self, agent: ConnectedAgent) -> None:
        if not self._supabase:
            return
        try:
            self._supabase.table("agent_connections").upsert({
                "agent_id": agent.agent_id,
                "org_id": self._org_id,
                "connected_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(agent.connected_at)
                ),
                "capabilities": agent.capabilities,
                "is_active": True,
            }, on_conflict="agent_id,org_id").execute()
        except Exception as exc:
            logger.debug("Agent registration persist failed: %s", exc)

    def _persist_signal(self, signal: AgentSignal) -> None:
        if not self._supabase:
            return
        try:
            self._supabase.table("agent_signals").insert({
                "agent_id": signal.agent_id,
                "org_id": signal.org_id,
                "signal_type": signal.signal_type,
                "payload": signal.payload,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(signal.timestamp)
                ),
            }).execute()
        except Exception as exc:
            logger.debug("Signal persist failed: %s", exc)
