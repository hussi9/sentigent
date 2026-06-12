"""
AgentHub — the central intelligence hub.

This is the moat: a singleton that all agents in an org connect to.
It reads their signals + prompts, learns collectively, and feeds better
intelligence back to each connected agent in real time.

  more agents → more signals → better intelligence → more agents join

Usage:
    from sentigent.intelligence import get_hub
    hub = get_hub()                         # start hub (singleton)
    hub.connect("my-agent-id")             # register this agent
    hub.publish_decision(agent_id, ...)    # publish a decision signal
    peers = hub.get_peer_patterns()         # get patterns from all peers

How it improves every agent:
  1. Peer patterns  — before a decision, check what similar tasks
                      produced across all org agents
  2. LLM enrichment — for ambiguous signals, Claude reasons with
                      full peer context (not just local history)
  3. Collective learning — thresholds auto-tune based on org-wide
                      outcome data, not just one agent's experience
  4. Cross-org wisdom — Layer 3 patterns optionally fed in
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Hub status
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HubStatus:
    running: bool
    org_id: str
    connected_agents: int
    total_signals_processed: int
    last_learn_cycle: float | None
    collective_score: float | None
    learner_report: dict | None


# ─────────────────────────────────────────────────────────────────────────────
# AgentHub
# ─────────────────────────────────────────────────────────────────────────────

class AgentHub:
    """
    Central intelligence hub. Singleton per org.

    Lifecycle: start() → agents connect → signals flow → learn continuously.
    """

    def __init__(
        self,
        org_id: str = "",
        memory_store: Any = None,
        policy_engine: Any = None,
        supabase_client: Any = None,
    ) -> None:
        self._org_id = org_id
        self._memory = memory_store
        self._policy_engine = policy_engine
        self._supabase = supabase_client
        self._running = False
        self._lock = threading.Lock()
        self._signals_processed = 0

        # Sub-components (lazy init)
        self._connector: Any = None
        self._llm_judge: Any = None
        self._learner: Any = None

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────

    def start(self) -> "AgentHub":
        if self._running:
            return self
        self._running = True

        # Connector: manages agent registration + signal queue
        from sentigent.intelligence.connector import AgentConnector
        self._connector = AgentConnector(
            org_id=self._org_id,
            supabase_client=self._supabase,
        )

        # LLM Judge: Claude reasoning for ambiguous decisions
        from sentigent.intelligence.llm_judge import LLMJudge
        self._llm_judge = LLMJudge(org_id=self._org_id)

        # Collective Learner: background self-improvement thread
        if self._memory:
            from sentigent.intelligence.learner import CollectiveLearner
            self._learner = CollectiveLearner(
                org_id=self._org_id,
                memory_store=self._memory,
                policy_engine=self._policy_engine,
                supabase_client=self._supabase,
            )
            self._learner.start()

        # Subscribe to all agent signals for hub-level processing
        self._connector.subscribe(self._on_signal)

        logger.info(
            "AgentHub started: org=%s, learner=%s, llm_judge=%s",
            self._org_id or "(local)",
            "active" if self._learner else "inactive",
            "active",
        )
        return self

    def stop(self) -> None:
        self._running = False
        if self._learner:
            self._learner.stop()
        logger.info("AgentHub stopped")

    # ──────────────────────────────────────────────────────────────────────
    # Agent connection API
    # ──────────────────────────────────────────────────────────────────────

    def connect(
        self,
        agent_id: str,
        capabilities: list[str] | None = None,
    ) -> None:
        """Register an agent with the hub."""
        if not self._running:
            self.start()
        self._connector.register(agent_id, capabilities=capabilities or [])

    def disconnect(self, agent_id: str) -> None:
        self._connector.unregister(agent_id)

    @property
    def connected_agents(self) -> list[Any]:
        if not self._connector:
            return []
        return self._connector.connected_agents

    # ──────────────────────────────────────────────────────────────────────
    # Signal publishing (called by engine.py on every evaluate/outcome)
    # ──────────────────────────────────────────────────────────────────────

    def publish_decision(
        self,
        agent_id: str,
        task: str,
        action: str,
        signals: dict[str, float],
        confidence: float,
        trace_id: str,
    ) -> None:
        """Called after every evaluate() — publishes the decision to the hub."""
        if not self._connector:
            return
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_DECISION
        self._connector.publish(AgentSignal(
            signal_type=SIGNAL_DECISION,
            agent_id=agent_id,
            org_id=self._org_id,
            payload={
                "task": task[:200],
                "action": action,
                "signals": signals,
                "confidence": confidence,
                "trace_id": trace_id,
            },
        ))

    def publish_outcome(
        self,
        agent_id: str,
        trace_id: str,
        outcome: str,
        task: str = "",
    ) -> None:
        """Called after every record_outcome() — feeds the learning loop."""
        if not self._connector:
            return
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_OUTCOME
        self._connector.publish(AgentSignal(
            signal_type=SIGNAL_OUTCOME,
            agent_id=agent_id,
            org_id=self._org_id,
            payload={"trace_id": trace_id, "outcome": outcome, "task": task[:200]},
        ))

    def publish_prompt(
        self,
        agent_id: str,
        task: str,
        quality_score: float,
        issues: list[str],
    ) -> None:
        """Called when a prompt quality assessment is done."""
        if not self._connector:
            return
        from sentigent.intelligence.connector import AgentSignal, SIGNAL_PROMPT
        self._connector.publish(AgentSignal(
            signal_type=SIGNAL_PROMPT,
            agent_id=agent_id,
            org_id=self._org_id,
            payload={"task": task[:200], "quality_score": quality_score, "issues": issues},
        ))

    # ──────────────────────────────────────────────────────────────────────
    # Intelligence retrieval (called by engine.py before deciding)
    # ──────────────────────────────────────────────────────────────────────

    def get_peer_patterns(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Return high-confidence patterns learned by peer agents in this org.
        Used to enrich LLM judge context + procedural rule matching.
        """
        if not self._supabase or not self._org_id:
            return []
        try:
            result = (
                self._supabase.table("org_patterns")
                .select(
                    "pattern_name,learned_action,success_rate,sample_size,"
                    "contributing_agents,last_reinforced"
                )
                .eq("org_id", self._org_id)
                .eq("is_active", True)
                .gte("success_rate", 0.80)
                .order("success_rate", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.debug("get_peer_patterns failed: %s", exc)
            return []

    def enrich_decision(
        self,
        agent_id: str,
        task: str,
        signals: dict[str, float],
        gate_action: str,
        gate_reason: str,
        similar_episodes: list[dict],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Try to improve the gate decision using LLM reasoning + peer context.

        Returns enriched decision dict or None if LLM judge not triggered.
        """
        if not self._llm_judge:
            return None

        peer_patterns = self.get_peer_patterns(limit=5)
        result = self._llm_judge.judge(
            task=task,
            signals=signals,
            gate_action=gate_action,
            gate_reason=gate_reason,
            similar_episodes=similar_episodes,
            peer_patterns=peer_patterns,
            context=context,
        )
        if result is None:
            return None

        return {
            "action": result.action,
            "reason": result.reason,
            "confidence": result.confidence,
            "model_used": result.model_used,
            "peer_context_used": result.peer_context_used,
            "latency_ms": result.latency_ms,
            "cached": result.cached,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────────────────────────────

    def status(self) -> HubStatus:
        learner_report = None
        if self._learner and self._learner.last_report:
            rpt = self._learner.last_report
            learner_report = {
                "agents_analyzed": rpt.agents_analyzed,
                "threshold_updates": len(rpt.threshold_updates),
                "policies_generated": len(rpt.policies_generated),
                "insights": rpt.cross_agent_insights,
                "regression_detected": rpt.regression_detected,
            }

        return HubStatus(
            running=self._running,
            org_id=self._org_id,
            connected_agents=self._connector.agent_count() if self._connector else 0,
            total_signals_processed=self._signals_processed,
            last_learn_cycle=(
                self._learner.last_report.timestamp
                if self._learner and self._learner.last_report else None
            ),
            collective_score=None,  # computed lazily
            learner_report=learner_report,
        )

    def get_agent_network(self) -> list[dict[str, Any]]:
        """Return metadata about all connected agents for the dashboard."""
        agents = self.connected_agents
        return [
            {
                "agent_id": a.agent_id,
                "connected_at": a.connected_at,
                "last_heartbeat": a.last_heartbeat,
                "judgment_score": a.judgment_score,
                "decision_count": a.decision_count,
                "is_alive": a.is_alive,
                "capabilities": a.capabilities,
            }
            for a in agents
        ]

    # ──────────────────────────────────────────────────────────────────────
    # Internal signal handler
    # ──────────────────────────────────────────────────────────────────────

    def _on_signal(self, signal: Any) -> None:
        with self._lock:
            self._signals_processed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_hub_lock = threading.Lock()
_hub_instance: AgentHub | None = None


def get_hub(
    org_id: str = "",
    memory_store: Any = None,
    policy_engine: Any = None,
    supabase_client: Any = None,
) -> AgentHub:
    """
    Return the singleton AgentHub, starting it if necessary.

    After the first call, subsequent calls return the same instance
    regardless of arguments (singleton pattern).
    """
    global _hub_instance
    with _hub_lock:
        if _hub_instance is None:
            resolved_org = org_id or os.environ.get("SENTIGENT_ORG_ID", "")

            # Try to get supabase if not provided
            if supabase_client is None:
                try:
                    from sentigent.dashboard.server import _get_supabase
                    supabase_client = _get_supabase()
                except Exception:
                    pass

            _hub_instance = AgentHub(
                org_id=resolved_org,
                memory_store=memory_store,
                policy_engine=policy_engine,
                supabase_client=supabase_client,
            )
            _hub_instance.start()

        return _hub_instance
