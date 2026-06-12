"""
sentigent.intelligence — Autonomous intelligence layer.

The moat: a central hub that reads signals + prompts from ALL connected
agents, learns collectively, and makes each agent smarter.

Network effect: more agents → more signals → better intelligence → more
agents join.

Quick start:
    from sentigent.intelligence import get_hub
    hub = get_hub()          # singleton, starts background loop
    hub.connect(agent_id)    # register this agent

Architecture:
    hub.py        — AgentHub: central intelligence hub (singleton)
    connector.py  — AgentConnector: registration + signal protocol
    llm_judge.py  — LLMJudge: Claude reasoning for ambiguous decisions
    learner.py    — CollectiveLearner: continuous cross-agent self-improvement
    agent_bus.py  — AgentBus: inter-agent messaging + capability routing
    executor.py   — ActionExecutor: decision → concrete side-effects
"""

from sentigent.intelligence.hub import AgentHub, get_hub
from sentigent.intelligence.agent_bus import AgentBus, get_agent_bus
from sentigent.intelligence.executor import ActionExecutor, get_executor

__all__ = ["AgentHub", "get_hub", "AgentBus", "get_agent_bus", "ActionExecutor", "get_executor"]
