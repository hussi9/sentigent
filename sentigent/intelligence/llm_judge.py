"""
LLMJudge — Claude-powered reasoning for ambiguous agent decisions.

Triggers when signals are in the ambiguous zone (caution 0.3–0.7, or high
conflict between signals). Uses context from all connected agents — not just
the calling agent — to reason about the right action.

Model routing:
  - claude-haiku-4-5  : default, fast (<400ms), cheap
  - claude-sonnet-4-6 : escalations + high-conflict signals

Caches by (task_fingerprint, signal_hash, org_id) for 60s to avoid
redundant LLM calls for similar tasks across agents.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

HAIKU   = "claude-haiku-4-5-20251001"
SONNET  = "claude-sonnet-4-6"

# Ambiguous zone: LLM judge kicks in when signals fall here
_AMBIGUOUS_LOW  = 0.30
_AMBIGUOUS_HIGH = 0.70


@dataclass
class JudgeResult:
    action: str                        # proceed | enrich | slow_down | escalate
    reason: str                        # human-readable explanation
    confidence: float                  # LLM confidence in its own answer 0-1
    model_used: str                    # which model answered
    peer_context_used: bool = False    # did we use cross-agent context?
    latency_ms: float = 0.0
    cached: bool = False


class LLMJudge:
    """Claude-powered reasoning engine for the intelligence hub."""

    def __init__(self, org_id: str = "") -> None:
        self._org_id = org_id
        self._cache: dict[str, tuple[float, JudgeResult]] = {}  # key → (expires_at, result)
        self._cache_ttl = 60.0  # seconds
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=os.environ.get("ANTHROPIC_API_KEY", "")
                )
            except ImportError:
                logger.warning("anthropic package not installed — LLM judge disabled")
        return self._client

    def _cache_key(self, task: str, signals: dict[str, float], peer_count: int) -> str:
        raw = json.dumps({
            "task": task[:200],
            "signals": {k: round(v, 1) for k, v in sorted(signals.items())},
            "peers": peer_count,
            "org": self._org_id,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _needs_llm(self, signals: dict[str, float], action: str) -> bool:
        """Return True when the rule-based gate is uncertain."""
        caution = signals.get("caution", 0.0)
        doubt   = signals.get("doubt", 0.0)
        conf    = signals.get("confidence", 0.0)

        if action == "escalate":
            return True  # always enrich escalations with LLM reasoning

        # Ambiguous zone: caution is middle-range
        if _AMBIGUOUS_LOW < caution < _AMBIGUOUS_HIGH:
            return True

        # High conflict: high caution AND high confidence (opposing signals)
        if caution > 0.5 and conf > 0.5:
            return True

        # High doubt with non-trivial caution
        if doubt > 0.5 and caution > 0.3:
            return True

        return False

    def _choose_model(self, action: str, signals: dict[str, float]) -> str:
        """Haiku default; Sonnet for escalations and high-conflict cases."""
        caution = signals.get("caution", 0.0)
        conf    = signals.get("confidence", 0.0)
        if action == "escalate" or (caution > 0.6 and conf > 0.5):
            return SONNET
        return HAIKU

    def judge(
        self,
        task: str,
        signals: dict[str, float],
        gate_action: str,
        gate_reason: str,
        similar_episodes: list[dict[str, Any]],
        peer_patterns: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> JudgeResult | None:
        """
        Ask Claude to reason about the decision.

        Returns None if LLM judgment is not needed or unavailable.
        Peer patterns from other connected agents are injected as context.
        """
        if not self._needs_llm(signals, gate_action):
            return None

        client = self._get_client()
        if not client:
            return None

        # Check cache
        peer_count = len(peer_patterns)
        cache_key = self._cache_key(task, signals, peer_count)
        now = time.monotonic()
        if cache_key in self._cache:
            expires_at, cached_result = self._cache[cache_key]
            if now < expires_at:
                cached_result.cached = True
                return cached_result

        model = self._choose_model(gate_action, signals)
        t0 = time.monotonic()

        # Build the prompt — ground Claude in signal data + peer context
        prompt = self._build_prompt(
            task=task,
            signals=signals,
            gate_action=gate_action,
            gate_reason=gate_reason,
            similar_episodes=similar_episodes[:3],
            peer_patterns=peer_patterns[:5],
            context=context,
        )

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are Sentigent, an AI judgment layer. Your job is to decide "
                    "whether an agent action should proceed, be enriched with more context, "
                    "slow down for caution, or escalate to a human. "
                    "Reply with JSON: {\"action\": \"...\", \"reason\": \"...\", \"confidence\": 0.0-1.0}"
                ),
            )
            text = resp.content[0].text.strip()
            # Extract JSON (may be wrapped in markdown)
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            parsed = json.loads(text)

            result = JudgeResult(
                action=parsed.get("action", gate_action),
                reason=parsed.get("reason", gate_reason),
                confidence=float(parsed.get("confidence", 0.7)),
                model_used=model,
                peer_context_used=bool(peer_patterns),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
            # Cache the result
            self._cache[cache_key] = (now + self._cache_ttl, result)
            return result

        except Exception as exc:
            logger.warning("LLM judge failed: %s", exc)
            return None

    def _build_prompt(
        self,
        task: str,
        signals: dict[str, float],
        gate_action: str,
        gate_reason: str,
        similar_episodes: list[dict],
        peer_patterns: list[dict],
        context: dict[str, Any],
    ) -> str:
        lines = [
            f"Task: {task}",
            "",
            "Signals (0=none, 1=max):",
        ]
        for k, v in signals.items():
            lines.append(f"  {k}: {v:.2f}")

        lines += ["", f"Rule-based decision: {gate_action}", f"Rule reason: {gate_reason}"]

        if similar_episodes:
            lines += ["", "Similar past decisions (this agent):"]
            for ep in similar_episodes:
                outcome = ep.get("outcome", "unknown")
                decision = ep.get("decision", "?")
                lines.append(f"  - decision={decision}, outcome={outcome}")

        if peer_patterns:
            lines += ["", "Peer agent patterns (other agents in this org learned):"]
            for p in peer_patterns:
                lines.append(
                    f"  - pattern={p.get('pattern_name','?')}, "
                    f"action={p.get('learned_action','?')}, "
                    f"success_rate={p.get('success_rate',0):.0%}, "
                    f"n={p.get('sample_size',0)}"
                )

        lines += [
            "",
            "Given these signals and what peer agents have learned, what is the right decision?",
            "Choices: proceed | enrich | slow_down | escalate",
        ]
        return "\n".join(lines)
