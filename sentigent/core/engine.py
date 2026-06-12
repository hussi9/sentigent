"""Sentigent — the main engine that ties everything together.

This is the primary public API. Users interact with Sentigent through:
- Sentigent(profile="financial_ops")  — create a judgment layer
- judge.evaluate(task, context, agent_state) — evaluate before an action
- judge.record_outcome(trace_id, outcome) — record what happened (async learning)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentigent.config import SentigentConfig, get_config
from sentigent.core.gate import DecisionGate
from sentigent.core.signals import SignalEngine
from sentigent.core.types import (
    BaselineStats,
    Decision,
    DecisionAction,
    Profile,
    Trace,
)
from sentigent.events import (
    EVENT_CIRCUIT_BREAKER,
    EVENT_JUDGMENT_MILESTONE,
    EVENT_OUTCOME,
    EVENT_PATTERN_DISCOVERED,
    SentigentEvent,
    get_event_bus,
)
from sentigent.learning.outcome import OutcomeAttributor
from sentigent.learning.pattern_miner import PatternMiner
from sentigent.memory.store import MemoryStore
from sentigent.observability import SpanContext, get_metrics, structured_log
from sentigent.profiles.registry import get_profile

logger = logging.getLogger("sentigent")


class Sentigent:
    """The judgment layer that learns.

    Main entry point for all Sentigent operations. Wraps signal computation,
    decision gating, memory storage, and learning into a single interface.

    Includes circuit breaker: if memory operations fail, evaluation degrades
    gracefully to profile-only defaults instead of raising exceptions.

    Usage:
        judge = Sentigent(profile="financial_ops")
        decision = judge.evaluate(
            task="Process refund for $50,000",
            context={"amount": 50000, "account_age_days": 45},
            agent_state={"step": "approve_refund", "confidence": 0.88}
        )
        # Later, when outcome is known:
        judge.record_outcome(decision.trace_id, "correct", "Fraud confirmed")
    """

    def __init__(
        self,
        profile: str | Profile = "default",
        agent_id: str | None = None,
        org_id: str | None = None,
        db_path: str | None = None,
        evaluate_timeout_ms: int | None = None,
        config: SentigentConfig | None = None,
    ) -> None:
        """Initialize Sentigent with a domain profile.

        When explicit parameters are not provided, falls back to configuration
        from sentigent.toml / environment variables / defaults (SERIOUS 4.3).

        Args:
            profile: Domain profile name (e.g., "financial_ops") or Profile object
            agent_id: Unique identifier for this agent instance
            org_id: Organization identifier (for Layer 2 learning)
            db_path: Path to SQLite database (default: ~/.sentigent/memory.db)
            evaluate_timeout_ms: Max time for evaluate() before circuit breaker kicks in
            config: Optional SentigentConfig override (otherwise uses global config)
        """
        # Load config for defaults when explicit params aren't provided
        cfg = config or get_config()

        if isinstance(profile, str):
            profile_name = profile if profile != "default" else cfg.profile
            self._profile = get_profile(profile_name)
        else:
            self._profile = profile

        self._agent_id = agent_id or cfg.agent_id
        self._org_id = org_id or cfg.org_id
        self._evaluate_timeout_ms = evaluate_timeout_ms or cfg.evaluate_timeout_ms
        self._config = cfg

        # Initialize components
        self._signal_engine = SignalEngine(self._profile)
        self._decision_gate = DecisionGate(self._profile)
        self._memory = MemoryStore(
            agent_id=self._agent_id,
            org_id=self._org_id,
            db_path=db_path or cfg.db_path,
        )

        # Learning components
        self._outcome_attributor = OutcomeAttributor()
        self._pattern_miner = PatternMiner()

        # Insights engine — computes structured findings from accumulated episodes
        from sentigent.core.insights import InsightsEngine
        self._insights = InsightsEngine(self._memory)

        # Counter for triggering periodic pattern mining (every 50 outcomes)
        self._outcome_counter: int = 0

        # Circuit breaker state
        self._memory_failures: int = 0
        self._memory_circuit_open: bool = False
        self._circuit_reset_after: int = 10  # Reset after 10 successful evals

        # Observability and events
        self._metrics = get_metrics()
        self._event_bus = get_event_bus()
        self._last_judgment_score: float = 0.0  # For milestone detection

        # Register configured webhooks from config/toml
        for event_type, urls in self._config.webhooks.items():
            for url in urls:
                self._event_bus.add_webhook(event_type, url)

        # Policy engine: org-wide enforcement (Layer 2)
        from sentigent.core.policy_engine import get_policy_engine
        self._policy_engine = get_policy_engine(
            org_id=self._org_id,
            profile=self._profile.name,
        )

        structured_log(
            logger, logging.INFO, "sentigent_initialized",
            agent_id=self._agent_id, profile=self._profile.name, org_id=self._org_id,
        )

        # Profile intelligence: org-level profile shapes signal scoring biases
        from sentigent.core.profile_intelligence import get_profile_intelligence
        self._profile_intelligence = get_profile_intelligence(
            org_id=self._org_id,
            agent_id=self._agent_id,
        )

        # Pull org patterns from Layer 2 into local rules on startup (non-blocking)
        self._pull_layer2_patterns()

        # Intelligence Hub: central hub connecting all agents in the org.
        # Starts a background learner, registers this agent, and enables
        # LLM-enriched decisions + peer pattern sharing.
        # Fails open — hub errors never break evaluate().
        self._hub: Any | None = None
        try:
            from sentigent.intelligence.hub import get_hub
            self._hub = get_hub(
                org_id=self._org_id,
                memory_store=self._memory,
                policy_engine=self._policy_engine,
            )
            self._hub.connect(
                self._agent_id,
                capabilities=["evaluate", "record_outcome", "layer2_sync"],
            )
        except Exception as _hub_err:
            logger.debug("Intelligence hub unavailable: %s", _hub_err)

        # Action Executor: translates decisions into concrete side-effects
        # (slow_down delays, escalation events, context enrichment).
        # Fails open — executor errors never break evaluate().
        try:
            from sentigent.intelligence.executor import get_executor
            self._executor = get_executor()
        except Exception:
            self._executor = None

    def _pull_layer2_patterns(self) -> None:
        """Pull org-wide patterns from Supabase into local procedural rules.

        This is how Layer 2 benefits the local agent: patterns learned by any
        agent in the org are pulled down and stored locally for fast-path decisions.
        Runs once at startup, silently skips if Supabase is not configured.
        """
        import os as _os
        if not _os.environ.get("SUPABASE_URL") or not (
            _os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or _os.environ.get("SUPABASE_ANON_KEY")
        ):
            return

        try:
            from sentigent.sync.manager import SyncManager
            sync = SyncManager(org_id=self._org_id, agent_id=self._agent_id)
            org_patterns = sync.pull_org_patterns(self._profile.name)

            imported = 0
            for pattern in org_patterns:
                # Only import patterns better than what we have locally
                existing = self._memory.get_matching_rules(
                    {"_lookup_by_name": pattern.get("pattern_name", "")}
                )
                # Store/update the org pattern in local procedural rules
                self._memory.store_procedural_rule({
                    "pattern_name": pattern["pattern_name"],
                    "condition": pattern.get("condition", {}),
                    "learned_action": pattern["learned_action"],
                    "success_rate": pattern.get("success_rate", 0),
                    "sample_size": pattern.get("sample_size", 0),
                })
                imported += 1

            if imported:
                logger.info(
                    "Pulled %d org patterns from Layer 2 (profile=%s)",
                    imported, self._profile.name,
                )
        except Exception as exc:
            logger.debug("Layer 2 pattern pull failed (non-critical): %s", exc)

    @property
    def judgment_score(self) -> float:
        """Current judgment accuracy score (0.0 to 1.0).

        Computed from the database: ratio of correct decisions to total
        evaluated decisions. Persists across restarts.
        Only includes decisions where an outcome has been recorded.
        """
        try:
            total, correct = self._memory.get_outcome_counts()
            if total == 0:
                return 0.0
            return correct / total
        except Exception:
            logger.warning("Failed to compute judgment score from DB, returning 0.0")
            return 0.0

    def evaluate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        agent_state: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> Decision:
        """Evaluate a task and produce a judgment decision.

        This is the main API. Call this before every agent action.
        Must complete in <50ms for production viability.

        Includes circuit breaker: if memory fails, falls back to profile defaults.

        Args:
            task: Description of the task/action the agent is about to take
            context: Full decision context (amounts, customer info, etc.)
            agent_state: Current agent state (step, confidence, retries, etc.)
            task_id: Optional task_id from start_task(). When provided, enables
                     scope enforcement and task-level outcome learning.

        Returns:
            Decision object with action, reason, signals, and judgment score
        """
        start_time = time.monotonic()
        context = context or {}
        agent_state = agent_state or {}

        # Step -2: Task context enforcement (Phase 2)
        # If a task_id is provided, retrieve the declared task and enforce scope.
        # Scope violations auto-escalate with a clear reason. Constraint violations
        # are injected into context as advisory notes for signal computation.
        # Fails open — task context is always additive, never blocking on error.
        if task_id:
            try:
                active_task = self._memory.get_active_task(task_id)
                if active_task and active_task.get("status") == "in_progress":
                    context["_task_id"] = task_id
                    context["_task_goal"] = active_task.get("goal", "")
                    context["_task_scope"] = active_task.get("scope", [])
                    context["_task_constraints"] = active_task.get("constraints", [])

                    # Scope enforcement: check if tool_input touches declared scope
                    tool_input_ref = context.get("tool_input", task)
                    declared_scope = active_task.get("scope", [])
                    if declared_scope:
                        in_scope = any(
                            s.lower() in tool_input_ref.lower() or tool_input_ref.lower() in s.lower()
                            for s in declared_scope
                        )
                        if not in_scope:
                            # Scope violation — auto-escalate
                            try:
                                self._memory.increment_scope_violations(task_id)
                            except Exception:
                                pass
                            scope_str = ", ".join(declared_scope[:5])
                            violation_decision = Decision(
                                action=DecisionAction.ESCALATE,
                                reason=(
                                    f"SCOPE VIOLATION: Action targets '{tool_input_ref[:80]}' "
                                    f"which is outside declared task scope [{scope_str}]. "
                                    f"Task goal: {active_task.get('goal', '')[:80]}. "
                                    "Confirm this action is intentional before proceeding."
                                ),
                                signals={},
                                signal_details=[],
                                judgment_score=self.judgment_score,
                                confidence=1.0,
                                metadata={
                                    "agent_id": self._agent_id,
                                    "source": "task_scope_enforcement",
                                    "task_id": task_id,
                                    "declared_scope": declared_scope,
                                },
                            )
                            self._safe_store_episode(task, context, agent_state or {}, {}, DecisionAction.ESCALATE, violation_decision)
                            return violation_decision

                    self._memory.increment_task_episodes(task_id)
            except Exception as _task_err:
                pass  # task context is always additive, never blocking

        # Step -1: Org policy enforcement (Layer 2) — highest priority
        # Org admin rules override everything else. Checked before any signal computation.
        tool_name = context.get("tool_name", "")
        policy_decision = self._check_org_policies(task, tool_name)
        if policy_decision.get("matched"):
            enforce_action_str = policy_decision["enforce_action"]
            try:
                enforce_action = DecisionAction(enforce_action_str)
            except ValueError:
                enforce_action = DecisionAction.SLOW_DOWN

            decision = Decision(
                action=enforce_action,
                reason=policy_decision["reason"],
                signals={},
                signal_details=[],
                judgment_score=self.judgment_score,
                confidence=1.0,  # policy enforcement is deterministic
                metadata={
                    "agent_id": self._agent_id,
                    "policy_name": policy_decision["policy_name"],
                    "policy_severity": policy_decision.get("severity", ""),
                    "source": "org_policy",
                },
            )
            elapsed = (time.monotonic() - start_time) * 1000
            self._metrics.increment("policy_enforcements_total", {"action": enforce_action_str})
            structured_log(
                logger, logging.INFO, "policy_enforced",
                policy_name=policy_decision["policy_name"],
                enforce_action=enforce_action_str,
                agent_id=self._agent_id,
                org_id=self._org_id,
            )
            self._safe_store_episode(task, context, agent_state, {}, enforce_action, decision)
            return decision

        # Step -0.5: Graph policy enforcement (Phase 6B)
        # Checks org relationship graph for entity-level policies.
        # Fires after flat policy engine but before signal computation.
        files_touched = context.get("files_touched") or context.get("scope") or []
        if isinstance(files_touched, str):
            files_touched = [files_touched]
        if not files_touched and tool_name in ("Edit", "Write", "Read"):
            # Extract file from tool_input if available
            tool_input_str = context.get("tool_input", "")
            if tool_input_str:
                files_touched = [tool_input_str[:200]]
        graph_policy_match = self._check_graph_policies(task, files_touched, context)
        if graph_policy_match:
            try:
                gp_action = DecisionAction(graph_policy_match.action)
            except ValueError:
                gp_action = DecisionAction.SLOW_DOWN
            decision = Decision(
                action=gp_action,
                reason=graph_policy_match.reason,
                signals={},
                signal_details=[],
                judgment_score=self.judgment_score,
                confidence=1.0,
                metadata={
                    "agent_id": self._agent_id,
                    "policy_name": graph_policy_match.policy_name,
                    "policy_severity": graph_policy_match.severity,
                    "matched_entity": graph_policy_match.matched_entity,
                    "source": "graph_policy",
                },
            )
            elapsed = (time.monotonic() - start_time) * 1000
            self._metrics.increment("policy_enforcements_total", {"action": gp_action.value})
            structured_log(
                logger, logging.INFO, "graph_policy_enforced",
                policy_name=graph_policy_match.policy_name,
                enforce_action=gp_action.value,
                matched_entity=graph_policy_match.matched_entity,
                agent_id=self._agent_id,
            )
            self._safe_store_episode(task, context, agent_state, {}, gp_action, decision)
            return decision

        # Step 0a: Enrich context with org profile intelligence (Layer 2 profile biases)
        # This injects value_weights and thresholds for the assigned org profile.
        # Fails open — any error just skips enrichment.
        try:
            context = self._profile_intelligence.enrich_context(context)
        except Exception:
            pass

        # Step 0b: Enrich context with org world model — Phase 3 domain-aware assembly
        # ContextAssembler classifies the domain (deploy/auth/data/finance/comms) and
        # pulls domain-specific knowledge layers. Injects critical entity severity hints,
        # entity relationships, and domain label. Always fails open.
        try:
            wm_additions = self._get_world_model_context(
                task=task,
                tool_name=tool_name,
                task_context={k: v for k, v in context.items() if k.startswith("_task_")},
            )
            if wm_additions:
                # Merge world model additions into context
                context.update({k: v for k, v in wm_additions.items()
                                if k not in ("_critical_entity_severity_hint",)})
                # Apply critical-entity severity boost
                hint = wm_additions.get("_critical_entity_severity_hint")
                if hint is not None:
                    existing = context.get("consequence_severity", 0.5)
                    context["consequence_severity"] = max(existing, hint)
        except Exception as _wm_err:
            pass  # world model is always additive


        # Step 0: Check procedural rules first (fast path for well-learned patterns)
        matching_rules = self._safe_get_matching_rules(context)
        for rule in matching_rules:
            if (
                rule.get("success_rate", 0) > 0.9
                and rule.get("sample_size", 0) > 50
            ):
                # High-confidence procedural rule — use it directly
                learned_action = rule["learned_action"]
                try:
                    action = DecisionAction(learned_action)
                except ValueError:
                    continue  # Skip invalid action values

                signal_strengths: dict[str, float] = {}
                decision = Decision(
                    action=action,
                    reason=f"Procedural rule '{rule['pattern_name']}' applied "
                           f"(success_rate={rule['success_rate']:.1%}, "
                           f"n={rule['sample_size']})",
                    signals=signal_strengths,
                    signal_details=[],
                    judgment_score=self.judgment_score,
                    confidence=rule["success_rate"],
                    metadata={
                        "agent_id": self._agent_id,
                        "procedural_rule_applied": rule["pattern_name"],
                        "rule_success_rate": rule["success_rate"],
                        "rule_sample_size": rule["sample_size"],
                    },
                )

                # Attach insight weights for observability and future signal tuning
                try:
                    cached_insights = self._insights.get_cached_insights()
                    weights = {
                        i.subject: i.signal_weight
                        for i in cached_insights
                        if i.confidence > 0.8 and i.signal_weight != 0
                    }
                    if weights:
                        decision.metadata["insight_weights"] = weights
                except Exception:
                    pass  # Never let insight lookup break evaluate()

                # Store trace in episodic memory
                self._safe_store_episode(task, context, agent_state, signal_strengths, action, decision)

                # Process pending attributions (non-critical, at end of evaluate)
                self._check_pending_attributions()

                elapsed = (time.monotonic() - start_time) * 1000
                logger.debug("evaluate() completed in %.1fms (procedural rule)", elapsed)
                return decision

        # Step 0b: Check advisory rules (failure patterns that survived /tmp)
        # These don't bypass evaluation but enrich the reason surfaced to the hook.
        advisory_note = ""
        for rule in matching_rules:
            cond = rule.get("condition", {})
            if isinstance(cond, str):
                try:
                    cond = json.loads(cond)
                except Exception:
                    cond = {}
            note = cond.get("advisory", "") if isinstance(cond, dict) else ""
            if note and rule.get("success_rate", 1.0) == 0.0:
                advisory_note = note
                break  # use first advisory match

        # Step 1: Get baselines (from memory layers, fallback to profile defaults)
        baselines = self._get_baselines(context)

        # Step 2: Find similar past episodes (Layer 1 memory)
        similar_episodes = self._safe_find_similar_episodes(task, context)

        # Step 3: Compute signals
        signals = self._signal_engine.compute_all(
            task=task,
            context=context,
            agent_state=agent_state,
            baselines=baselines,
            similar_episodes=similar_episodes,
        )

        # Step 4: Decision gate (with session context)
        action, reason = self._decision_gate.decide(signals, task_summary=task)

        # Step 5: Build decision object
        signal_strengths = {s.type.value: s.strength for s in signals}

        # Prepend advisory note if a learned failure pattern applies
        full_reason = f"{advisory_note} | {reason}" if advisory_note else reason

        decision = Decision(
            action=action,
            reason=full_reason,
            signals=signal_strengths,
            signal_details=signals,
            judgment_score=self.judgment_score,
            confidence=self._compute_decision_confidence(signals),
            metadata={
                "agent_id": self._agent_id,
                "task_id": task_id or None,
                "baselines_source": {
                    name: stat.source for name, stat in baselines.items()
                },
                "similar_episodes_count": len(similar_episodes) if similar_episodes else 0,
                "memory_circuit_open": self._memory_circuit_open,
                "advisory_note": advisory_note or None,
            },
        )

        # Attach insight weights for observability and future signal tuning
        try:
            cached_insights = self._insights.get_cached_insights()
            weights = {
                i.subject: i.signal_weight
                for i in cached_insights
                if i.confidence > 0.8 and i.signal_weight != 0
            }
            if weights:
                decision.metadata["insight_weights"] = weights
        except Exception:
            pass  # Never let insight lookup break evaluate()

        # Prompt quality intercept: flag vague tasks and suggest the builder
        try:
            from sentigent.core.prompt_builder import assess_prompt_quality
            pq = assess_prompt_quality(task)
            if pq["vague"]:
                decision.metadata["prompt_quality"] = {
                    "score": pq["score"],
                    "issues": pq.get("issues", []),
                    "suggestion": pq.get("suggestion", ""),
                    "suggested_template": pq.get("suggested_template", "product_spec"),
                }
                # Publish prompt quality signal to intelligence hub
                if self._hub:
                    try:
                        self._hub.publish_prompt(
                            agent_id=self._agent_id,
                            task=task,
                            quality_score=pq["score"],
                            issues=pq.get("issues", []),
                        )
                    except Exception:
                        pass
        except Exception:
            pass  # Never let prompt quality check break evaluate()

        # Intelligence Hub: enrich decision with LLM reasoning + peer patterns.
        # Only triggers for ambiguous signals — fast-path cases are unaffected.
        # Fails open: any hub error leaves original decision unchanged.
        if self._hub:
            try:
                enriched = self._hub.enrich_decision(
                    agent_id=self._agent_id,
                    task=task,
                    signals=signal_strengths,
                    gate_action=action.value,
                    gate_reason=full_reason,
                    similar_episodes=(
                        [
                            {"task": ep.get("task", ""), "decision": ep.get("decision", ""),
                             "outcome": ep.get("outcome", "")}
                            for ep in similar_episodes
                        ] if similar_episodes else []
                    ),
                    context=context,
                )
                if enriched:
                    try:
                        enriched_action = DecisionAction(enriched["action"])
                    except ValueError:
                        enriched_action = action
                    decision.action = enriched_action
                    decision.reason = enriched["reason"]
                    decision.confidence = max(decision.confidence, enriched["confidence"])
                    decision.metadata["hub_enriched"] = {
                        "model": enriched.get("model_used"),
                        "peer_context": enriched.get("peer_context_used"),
                        "latency_ms": enriched.get("latency_ms"),
                        "cached": enriched.get("cached"),
                    }
            except Exception:
                pass  # Hub enrichment is best-effort

        # Step 6: Store trace in episodic memory
        self._safe_store_episode(task, context, agent_state, signal_strengths, action, decision)

        # Step 7: Process pending attributions (lazy — processes old episodes, not current)
        self._check_pending_attributions()

        # Intelligence Hub: publish decision signal so peer agents can learn from it.
        if self._hub:
            try:
                self._hub.publish_decision(
                    agent_id=self._agent_id,
                    task=task,
                    action=decision.action.value,
                    signals=signal_strengths,
                    confidence=decision.confidence,
                    trace_id=decision.trace_id,
                )
            except Exception:
                pass

        elapsed = (time.monotonic() - start_time) * 1000

        # Observability: metrics and structured logging
        self._metrics.increment("decisions_total", {"action": action.value})
        self._metrics.record_latency("evaluate_latency_ms", elapsed)
        structured_log(
            logger, logging.INFO, "evaluate_complete",
            action=action.value, confidence=round(decision.confidence, 3),
            judgment_score=round(decision.judgment_score, 3),
            latency_ms=round(elapsed, 1), task=task[:80],
            agent_id=self._agent_id,
        )
        if elapsed > self._evaluate_timeout_ms:
            self._metrics.increment("evaluate_timeout")
            structured_log(
                logger, logging.WARNING, "evaluate_timeout",
                latency_ms=round(elapsed, 1),
                timeout_ms=self._evaluate_timeout_ms,
            )

        # Action Executor: fire concrete side-effects for this decision
        # (escalation events, slow_down delay, enrich context, etc.)
        if self._executor:
            try:
                exec_result = self._executor.execute(
                    action=decision.action.value,
                    agent_id=self._agent_id,
                    task=task,
                    trace_id=decision.trace_id,
                    confidence=decision.confidence,
                    signals=signal_strengths,
                    reason=decision.reason,
                    context=context,
                    org_id=self._org_id,
                )
                if exec_result.enriched_context:
                    decision.metadata["executor_enrichment"] = exec_result.enriched_context
                if exec_result.slow_down_ms:
                    decision.metadata["slow_down_ms"] = exec_result.slow_down_ms
            except Exception:
                pass  # executor never breaks evaluate()

        return decision

    def record_outcome(
        self,
        trace_id: str,
        outcome: str,
        feedback: str | None = None,
    ) -> None:
        """Record the outcome of a previous decision. This is how the agent learns.

        Call this when you know whether a decision was correct or not.
        The learning loop will:
        1. Update the trace with the outcome
        2. Adjust baselines based on the result
        3. Reinforce or weaken learned patterns

        Args:
            trace_id: The trace_id from the Decision object
            outcome: "correct", "incorrect", or "neutral"
            feedback: Optional human feedback explaining the outcome
        """
        try:
            self._memory.record_outcome(
                trace_id=trace_id,
                outcome=outcome,
                feedback=feedback,
                timestamp=datetime.now(timezone.utc),
            )

            # Trigger learning: update baselines from accumulated experience
            self._memory.update_baselines_from_episodes()

            # Track outcomes and periodically mine patterns
            if outcome in ("correct", "incorrect"):
                self._outcome_counter += 1
                self._maybe_mine_patterns()
                self._maybe_sync_layer2()
                # Refresh insights every 10 outcomes
                if self._outcome_counter % 10 == 0:
                    self._insights.refresh_if_stale()

            # Observability: metrics and structured logging
            current_score = self.judgment_score
            self._metrics.increment("outcomes_total", {"outcome": outcome})
            structured_log(
                logger, logging.INFO, "outcome_recorded",
                trace_id=trace_id[:8], outcome=outcome,
                judgment_score=round(current_score, 3),
                agent_id=self._agent_id,
            )

            # Events: outcome event
            self._event_bus.emit(EVENT_OUTCOME, SentigentEvent(
                event_type=EVENT_OUTCOME,
                trace_id=trace_id,
                agent_id=self._agent_id,
                metadata={"outcome": outcome, "judgment_score": current_score},
            ))

            # Events: judgment milestone detection
            self._check_judgment_milestones(current_score)

            # Intelligence Hub: publish outcome so collective learner picks it up
            if self._hub:
                try:
                    self._hub.publish_outcome(
                        agent_id=self._agent_id,
                        trace_id=trace_id,
                        outcome=outcome,
                    )
                except Exception:
                    pass

        except Exception as exc:
            logger.error("Failed to record outcome for trace %s: %s", trace_id[:8], exc)

    def start_task(
        self,
        goal: str,
        scope: list[str] | None = None,
        authorized_by: str = "user",
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        task_id: str | None = None,
    ) -> str:
        """Declare a task and return its task_id.

        Call this BEFORE the first evaluate() of a new task. The returned
        task_id should be passed to all subsequent evaluate() calls so that
        Sentigent can enforce scope, track constraint memory, and attribute
        outcomes at the task level rather than the episode level.

        Args:
            goal: What the agent is trying to accomplish
            scope: Files, services, or resources the agent is authorized to touch
            authorized_by: Who authorized this task ('user' | 'policy' | 'org_admin')
            success_criteria: Observable signals that indicate task completion
            constraints: Explicit constraints (what NOT to do)
            task_id: Optional custom task_id (defaults to a new UUID)

        Returns:
            task_id: Pass this to evaluate() and complete_task()
        """
        import uuid as _uuid
        tid = task_id or str(_uuid.uuid4())

        try:
            self._memory.start_task(
                task_id=tid,
                goal=goal,
                scope=scope or [],
                authorized_by=authorized_by,
                success_criteria=success_criteria or [],
                constraints=constraints or [],
            )
            structured_log(
                logger, logging.INFO, "task_started",
                task_id=tid[:8], goal=goal[:80],
                scope_count=len(scope or []),
                agent_id=self._agent_id,
            )
        except Exception as exc:
            logger.warning("Failed to persist task start: %s", exc)

        return tid

    def complete_task(
        self,
        task_id: str,
        outcome: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Mark a task as complete with its outcome.

        Call this when the task is done (or abandoned). Records the task-level
        outcome which feeds the pattern miner at the task level (not just the
        episode level) and syncs to Layer 2 for org-wide learning.

        Args:
            task_id: The task_id returned by start_task()
            outcome: 'correct' | 'incorrect' | None (None = abandoned/unknown)
            summary: Optional human-readable summary of what was accomplished
        """
        try:
            self._memory.complete_task(
                task_id=task_id,
                outcome=outcome,
                summary=summary,
            )
            structured_log(
                logger, logging.INFO, "task_completed",
                task_id=task_id[:8], outcome=outcome or "abandoned",
                agent_id=self._agent_id,
            )
        except Exception as exc:
            logger.warning("Failed to persist task completion: %s", exc)

    def _get_baselines(self, context: dict[str, Any]) -> dict[str, BaselineStats]:
        """Get the best available baselines for the given context.

        Priority: Layer 1 (agent) > Layer 2 (org) > Layer 3 (collective) > Profile defaults
        """
        baselines: dict[str, BaselineStats] = {}

        # Start with profile defaults
        for key, value in self._profile.world_model.baselines.items():
            if isinstance(value, dict) and "median" in value:
                baselines[key] = BaselineStats(
                    metric_name=key,
                    median=value.get("median", 0),
                    mean=value.get("mean", value.get("median", 0)),
                    std=value.get("std", value.get("median", 0) * 0.5),
                    p5=value.get("p5", 0),
                    p25=value.get("p25", 0),
                    p75=value.get("p75", 0),
                    p95=value.get("p95", 0),
                    source="profile_default",
                )

        # Override with learned baselines from memory (Layer 1)
        if not self._memory_circuit_open:
            try:
                learned = self._memory.get_baselines()
                for key, stats in learned.items():
                    baselines[key] = stats
                self._memory_failures = 0  # Reset on success
            except Exception as exc:
                self._memory_failures += 1
                logger.warning(
                    "Memory baseline fetch failed (%d/%d): %s",
                    self._memory_failures, self._circuit_reset_after, exc,
                )
                if self._memory_failures >= 3:
                    self._memory_circuit_open = True
                    self._metrics.increment("circuit_breaker_open")
                    structured_log(
                        logger, logging.ERROR, "circuit_breaker_open",
                        agent_id=self._agent_id, source="get_baselines",
                    )
                    self._event_bus.emit(EVENT_CIRCUIT_BREAKER, SentigentEvent(
                        event_type=EVENT_CIRCUIT_BREAKER,
                        agent_id=self._agent_id,
                        reason="Memory baseline fetch failures exceeded threshold",
                    ))

        return baselines

    def _compute_decision_confidence(self, signals: list[Any]) -> float:
        """Compute Sentigent's confidence in its own decision.

        Higher when signals are clear and consistent.
        Lower when signals conflict or are ambiguous.
        """
        strengths = [s.strength for s in signals]
        if not strengths:
            return 0.5

        # High confidence when one signal dominates (clear situation)
        max_strength = max(strengths)
        mean_strength = sum(strengths) / len(strengths)

        # If max is much higher than mean, the situation is clear
        clarity = max_strength - mean_strength if max_strength > 0.3 else 0.5

        # Combine with judgment score (experience matters)
        return min(1.0, clarity * 0.6 + self.judgment_score * 0.4)

    def _check_pending_attributions(self) -> None:
        """Process old episodes without outcomes for absence-based attribution.

        Looks at recent episodes that still lack outcomes and checks whether
        enough time has passed (absence window) to infer a 'correct' outcome.
        """
        if self._memory_circuit_open:
            return

        try:
            pending = self._memory.get_pending_episodes(
                agent_id=self._agent_id, limit=100,
            )

            for trace in pending:
                attribution = self._outcome_attributor.check_absence_attribution(trace)
                if attribution is not None:
                    self._memory.record_outcome(
                        trace_id=attribution["trace_id"],
                        outcome=attribution["outcome"],
                        feedback=attribution.get("reason", "Auto-attributed by absence inference"),
                        timestamp=datetime.now(timezone.utc),
                    )
        except Exception as exc:
            logger.debug("Pending attribution check failed: %s", exc)

    def _maybe_mine_patterns(self) -> None:
        """Periodically mine patterns from accumulated episodes.

        Runs every 10 recorded outcomes (checked against DB total, so it works
        correctly even when Sentigent is instantiated fresh per hook call).
        Discovered patterns are stored as procedural rules for fast-path decisions.
        """
        try:
            # Use DB total so this works across fresh instances (e.g. per-hook-call)
            stats = self._memory.get_outcome_stats()
            total = sum(stats.values())
            if total == 0 or total % 10 != 0:
                return
        except Exception:
            return

        try:
            episodes = self._memory.get_episodes_with_outcomes(
                agent_id=self._agent_id, limit=1000,
            )

            if not episodes:
                return

            patterns = self._pattern_miner.mine_patterns(episodes)
            for pattern in patterns:
                self._memory.store_procedural_rule(pattern)

            if patterns:
                self._metrics.increment("pattern_mines_total")
                structured_log(
                    logger, logging.INFO, "patterns_mined",
                    count=len(patterns), episodes=len(episodes),
                    agent_id=self._agent_id,
                )
                for pattern in patterns:
                    self._event_bus.emit(EVENT_PATTERN_DISCOVERED, SentigentEvent(
                        event_type=EVENT_PATTERN_DISCOVERED,
                        agent_id=self._agent_id,
                        metadata={
                            "pattern_name": pattern.get("pattern_name", ""),
                            "success_rate": pattern.get("success_rate", 0),
                            "sample_size": pattern.get("sample_size", 0),
                        },
                    ))
        except Exception as exc:
            logger.debug("Pattern mining failed: %s", exc)

        # Also promote persistent Bash failures to procedural rules
        self._promote_bash_failures()

    def _get_world_model_context(
        self,
        task: str,
        tool_name: str,
        task_context: dict | None = None,
    ) -> dict:
        """Phase 3: Domain-aware context assembly from org knowledge layers.

        Replaces the generic keyword dump with ContextAssembler — classifies
        the evaluation domain first, then pulls the right knowledge layers for
        that domain (deploy → blast radius, auth → security + approvers, etc.).

        Returns a pre-merged context dict ready to update the evaluate() context.
        Empty dict on any error — always fails open.
        """
        import os as _os
        supabase_url = _os.environ.get("SUPABASE_URL", "")
        has_key = bool(
            _os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or _os.environ.get("SUPABASE_ANON_KEY")
        )
        if not supabase_url or not has_key or not self._org_id:
            return {}
        try:
            from sentigent.sync.manager import _get_supabase_client as _get_sb
            from sentigent.core.context_assembler import ContextAssembler, classify_domain
            client = _get_sb()
            domain = classify_domain(task, tool_name)
            assembler = ContextAssembler(client, self._org_id)
            return assembler.assemble(
                task=task,
                tool_name=tool_name,
                domain=domain,
                agent_id=self._agent_id,
                task_context=task_context,
            )
        except Exception as exc:
            logger.debug("world model context unavailable: %s", exc)
            return {}

        try:
            from sentigent.sync.manager import _get_supabase_client as _get_sb
            from sentigent.memory.world_model import WorldModelQuery
            client = _get_sb()
            query = WorldModelQuery(client, self._org_id)
            return query.get_context(
                task=task,
                tool_name=tool_name,
                agent_id=self._agent_id,
            )
        except Exception as exc:
            logger.debug("world model context unavailable: %s", exc)
            return None

    def _check_org_policies(self, task: str, tool_name: str) -> dict:
        """Check org-level policies before individual judgment.

        Returns a dict with matched=True/False and policy details if matched.
        Fails open (returns matched=False) if policy engine raises.
        """
        try:
            result = self._policy_engine.check(tool_name=tool_name, task=task)
            if result.matched:
                # Log violation to Supabase asynchronously (best-effort)
                try:
                    self._policy_engine.record_violation(
                        agent_id=self._agent_id,
                        policy_name=result.policy_name,
                        task=task,
                        tool_name=tool_name,
                        enforced_action=result.enforce_action,
                    )
                except Exception:
                    pass
                return {
                    "matched": True,
                    "policy_name": result.policy_name,
                    "enforce_action": result.enforce_action,
                    "reason": result.reason,
                    "severity": result.severity,
                }
        except Exception as exc:
            logger.debug("Policy engine check failed (failing open): %s", exc)
        return {"matched": False}

    def _check_graph_policies(
        self,
        task: str,
        files_touched: list[str],
        context: dict,
    ) -> "Any | None":
        """Check graph-based policies (Phase 6B). Fails open (returns None)."""
        try:
            from sentigent.core.graph_policy import GraphPolicyEngine
            gpe = GraphPolicyEngine(db_path=self._store.db_path, org_id=self._org_id)
            return gpe.evaluate(files_touched=files_touched, task=task, context=context)
        except Exception as exc:
            logger.debug("Graph policy check failed (failing open): %s", exc)
            return None

    def _promote_bash_failures(self) -> None:
        """Promote repeated Bash failures from /tmp into persistent procedural rules.

        When the same Bash command prefix has failed 3+ times (tracked by the
        PostToolUse hook), it gets stored as a procedural rule with success_rate=0.0.
        This makes the failure advisory persistent across sessions and visible in
        the dashboard patterns table, rather than being lost on next /tmp flush.

        Threshold: 3+ failures for the same command prefix.
        """
        import time
        fail_file = Path("/tmp/sentigent_bash_failures.json")
        if not fail_file.exists():
            return

        try:
            failures = json.loads(fail_file.read_text())
        except Exception:
            return

        if not failures:
            return

        # Group by command prefix (first word)
        from collections import defaultdict
        by_prefix: dict[str, list[dict]] = defaultdict(list)
        for f in failures:
            cmd = f.get("command", "")
            prefix = cmd.split()[0] if cmd.split() else ""
            if prefix:
                by_prefix[prefix].append(f)

        promoted = 0
        for prefix, entries in by_prefix.items():
            if len(entries) < 3:
                continue  # not enough signal yet

            last = entries[-1]
            pattern_name = f"bash_failure_{prefix}"
            suggested_tool = last.get("suggested_tool", "mcp__desktop-commander")
            advisory = (
                f"Bash({prefix}) has failed {len(entries)} times. "
                f"Use {suggested_tool} instead."
            )

            rule: dict = {
                "pattern_name": pattern_name,
                "agent_id": self._agent_id,
                "learned_action": "slow_down",
                "success_rate": 0.0,
                "sample_size": len(entries),
                "condition": json.dumps({"advisory": advisory, "cmd_prefix": prefix}),
                "last_reinforced": datetime.fromtimestamp(
                    last.get("ts", time.time()), tz=timezone.utc,
                ).isoformat(),
            }

            try:
                self._memory.store_procedural_rule(rule)
                promoted += 1
            except Exception as exc:
                logger.debug("Failed to promote bash failure rule %s: %s", pattern_name, exc)

        if promoted:
            self._metrics.increment("bash_failures_promoted", {"count": str(promoted)})
            structured_log(
                logger, logging.INFO, "bash_failures_promoted",
                count=promoted, agent_id=self._agent_id,
            )

    def _maybe_sync_layer2(self) -> None:
        """Sync recent episodes + learned patterns to Supabase (Layer 2).

        Runs every 10 recorded outcomes when SUPABASE_URL and a key are set.
        Non-blocking: failures are logged but never propagate to the caller.
        """
        import os as _os

        # Only run when Supabase is configured
        supabase_url = _os.environ.get("SUPABASE_URL", "")
        has_key = bool(
            _os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or _os.environ.get("SUPABASE_ANON_KEY")
        )
        if not supabase_url or not has_key or self._memory_circuit_open:
            return

        # Only sync every 10 outcomes (checked via DB total)
        try:
            stats = self._memory.get_outcome_stats()
            total = sum(stats.values())
            if total == 0 or total % 10 != 0:
                return
        except Exception:
            return

        try:
            from sentigent.sync.manager import SyncManager

            sync = SyncManager(
                org_id=self._org_id,
                agent_id=self._agent_id,
            )

            # Push recent episodes with outcomes
            episodes = self._memory.get_episodes_with_outcomes(
                agent_id=self._agent_id, limit=200,
            )
            if episodes:
                result = sync.push_episodes(episodes)
                logger.debug(
                    "Layer 2 sync: %d synced, %d failed",
                    result["synced"], result["failed"],
                )

            # Push the latest learned procedural rules
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(self._memory.db_path)
            conn.row_factory = _sqlite3.Row
            rules = conn.execute(
                "SELECT * FROM procedural_rules WHERE agent_id = ? ORDER BY last_reinforced DESC LIMIT 20",
                (self._agent_id,),
            ).fetchall()
            conn.close()

            patterns_to_push = []
            for rule in rules:
                pattern = {
                    "pattern_name": rule["pattern_name"],
                    "condition": rule["condition"],
                    "learned_action": rule["learned_action"],
                    "success_rate": rule["success_rate"],
                    "sample_size": rule["sample_size"],
                }
                sync.push_pattern(pattern, profile_name=self._profile.name)
                patterns_to_push.append(pattern)

            # Auto-contribute high-confidence patterns to Layer 3 (if opted in)
            if patterns_to_push:
                l3_result = sync.contribute_to_layer3(
                    patterns_to_push, profile_name=self._profile.name
                )
                if l3_result["contributed"] > 0:
                    logger.debug(
                        "Layer 3 auto-contribute: %d patterns → collective pool",
                        l3_result["contributed"],
                    )

            # Every 100 outcomes, trigger server-side baseline recompute
            if total % 100 == 0:
                sync.trigger_org_baseline_recompute(self._profile.name)

        except Exception as exc:
            logger.debug("Layer 2 sync failed (non-critical): %s", exc)

    def _check_judgment_milestones(self, current_score: float) -> None:
        """Emit events when judgment score crosses milestone thresholds."""
        milestones = (0.5, 0.7, 0.8, 0.9)
        for milestone in milestones:
            if current_score >= milestone and self._last_judgment_score < milestone:
                self._event_bus.emit(EVENT_JUDGMENT_MILESTONE, SentigentEvent(
                    event_type=EVENT_JUDGMENT_MILESTONE,
                    agent_id=self._agent_id,
                    metadata={
                        "milestone": milestone,
                        "judgment_score": current_score,
                        "previous_score": self._last_judgment_score,
                    },
                ))
                structured_log(
                    logger, logging.INFO, "judgment_milestone",
                    milestone=milestone, score=round(current_score, 3),
                    agent_id=self._agent_id,
                )
        self._last_judgment_score = current_score

    # ── Circuit Breaker Safe Wrappers ──────────────────────────────────────

    def _safe_get_matching_rules(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Get matching rules with circuit breaker protection."""
        if self._memory_circuit_open:
            return []
        try:
            return self._memory.get_matching_rules(context)
        except Exception as exc:
            logger.debug("get_matching_rules failed: %s", exc)
            return []

    def _safe_find_similar_episodes(
        self, task: str, context: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Find similar episodes with circuit breaker protection."""
        if self._memory_circuit_open:
            return None
        try:
            return self._memory.find_similar_episodes(task, context=context, limit=10)
        except Exception as exc:
            logger.debug("find_similar_episodes failed: %s", exc)
            return None

    def _safe_store_episode(
        self,
        task: str,
        context: dict[str, Any],
        agent_state: dict[str, Any],
        signal_strengths: dict[str, float],
        action: DecisionAction,
        decision: Decision,
    ) -> None:
        """Store an episode trace with circuit breaker protection."""
        if self._memory_circuit_open:
            return
        try:
            trace = Trace(
                trace_id=decision.trace_id,
                agent_id=self._agent_id,
                task=task,
                context=context,
                agent_state=agent_state,
                signals=signal_strengths,
                decision=action,
                reason=decision.reason,
                confidence_at_decision=decision.confidence,
            )
            self._memory.store_episode(trace)
            self._metrics.increment("episodes_stored_total")
        except Exception as exc:
            self._memory_failures += 1
            self._metrics.increment("memory_failures_total")
            logger.warning("Failed to store episode: %s", exc)
            if self._memory_failures >= 3:
                self._memory_circuit_open = True
                self._metrics.increment("circuit_breaker_open")
                structured_log(
                    logger, logging.ERROR, "circuit_breaker_open",
                    agent_id=self._agent_id, failures=self._memory_failures,
                )
                self._event_bus.emit(EVENT_CIRCUIT_BREAKER, SentigentEvent(
                    event_type=EVENT_CIRCUIT_BREAKER,
                    agent_id=self._agent_id,
                    reason="Memory failures exceeded threshold",
                    metadata={"failure_count": self._memory_failures},
                ))
