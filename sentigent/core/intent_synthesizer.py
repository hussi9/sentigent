"""IntentSynthesizer — synthesizes a structured SENTIGENT_INTENT block at session start."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore
    from sentigent.sync.manager import SyncManager


@dataclass
class SentigentIntentBlock:
    """Structured intent context injected at session start."""

    objective: str
    constraints: list[str]
    relevant_history: list[dict[str, Any]]
    recommended_skill: str
    recommended_model: str
    routing_confidence: float
    success_signals: list[str]
    cold_start: bool

    def to_context_block(self) -> str:
        """Format as YAML-like string for injection into agent context."""
        lines = [
            "--- SENTIGENT_INTENT ---",
            f"objective: {self.objective}",
        ]
        if self.constraints:
            lines.append("constraints:")
            for c in self.constraints:
                lines.append(f"  - {c}")
        if self.relevant_history:
            lines.append("relevant_history:")
            for ep in self.relevant_history[:3]:
                task = ep.get("task", "")[:80]
                lines.append(f"  - task: {task}")
                lines.append(f"    decision: {ep.get('decision', '')}")
                lines.append(f"    outcome: {ep.get('outcome', '')}")
        if self.recommended_skill:
            lines.append(f"recommended_skill: {self.recommended_skill}")
        lines.append(f"recommended_model: {self.recommended_model}")
        lines.append(f"routing_confidence: {self.routing_confidence:.2f}")
        if self.success_signals:
            lines.append("success_signals:")
            for s in self.success_signals:
                lines.append(f"  - {s}")
        if self.cold_start:
            lines.append(
                "note: cold_start=true — fewer than 20 episodes; routing may be imprecise"
            )
        lines.append("---")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": self.constraints,
            "relevant_history": self.relevant_history,
            "recommended_skill": self.recommended_skill,
            "recommended_model": self.recommended_model,
            "routing_confidence": self.routing_confidence,
            "success_signals": self.success_signals,
            "cold_start": self.cold_start,
        }


class IntentSynthesizer:
    """Synthesize a SENTIGENT_INTENT block from memory + routing + org patterns."""

    def synthesize(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        store: "MemoryStore | None" = None,
        sync_manager: "SyncManager | None" = None,
    ) -> SentigentIntentBlock:
        context = context or {}

        routing_skill, routing_model, routing_confidence = self._route(task, store)
        relevant_history = self._get_history(task, store)
        cold_start = self._is_cold_start(store)
        constraints = self._get_constraints(sync_manager)
        objective, success_signals = self._extract_intent(task)

        return SentigentIntentBlock(
            objective=objective,
            constraints=constraints,
            relevant_history=relevant_history,
            recommended_skill=routing_skill,
            recommended_model=routing_model,
            routing_confidence=routing_confidence,
            success_signals=success_signals,
            cold_start=cold_start,
        )

    def _route(self, task: str, store: "MemoryStore | None") -> tuple[str, str, float]:
        if store is None:
            return "", "sonnet", 0.0
        try:
            from sentigent.routing.matcher import match_seeds
            matches = match_seeds(task, store)
            if matches:
                best = matches[0]
                return best.skill, best.model, best.confidence
        except Exception:
            logger.debug("intent routing failed", exc_info=True)
        return "", "sonnet", 0.0

    def _get_history(self, task: str, store: "MemoryStore | None") -> list[dict[str, Any]]:
        if store is None:
            return []
        try:
            episodes = store.find_similar_episodes(task, limit=3)
            return [
                {
                    "task": ep.get("task", ""),
                    "decision": ep.get("decision", ""),
                    "outcome": ep.get("outcome", ""),
                }
                for ep in episodes
            ]
        except Exception:
            logger.debug("episode retrieval failed", exc_info=True)
            return []

    def _is_cold_start(self, store: "MemoryStore | None") -> bool:
        if store is None:
            return True
        try:
            return store.get_episode_count() < 20
        except Exception:
            logger.debug("cold start check failed", exc_info=True)
            return True

    def _get_constraints(self, sync_manager: "SyncManager | None") -> list[str]:
        if sync_manager is None:
            return []
        try:
            patterns = sync_manager.pull_org_patterns("default")
            return [
                f"Pattern '{p.get('pattern_name', '')}' → {p.get('learned_action', '')}"
                for p in patterns[:5]
                if p.get("learned_action") in ("block", "escalate")
            ]
        except Exception:
            logger.debug("constraint retrieval failed", exc_info=True)
            return []

    def _extract_intent(self, task: str) -> tuple[str, list[str]]:
        try:
            from sentigent.core.intent_extractor import IntentExtractor
            extracted = IntentExtractor().extract(task)
            goal = extracted.goal or task[:120]
            signals = extracted.success_criteria or [
                "Task completes without errors",
                "Output matches specification",
            ]
            return goal, signals
        except Exception:
            logger.debug("intent extraction failed", exc_info=True)
            return task[:120], ["Task completes without errors"]
