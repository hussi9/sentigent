"""LangGraph integration — deep hooks into LangGraph agent lifecycle.

Provides decorators and utilities to seamlessly integrate Sentigent
with LangGraph workflows.

Usage:
    from sentigent import Sentigent
    from sentigent.integrations.langgraph import SentigentNode, wrap_node

    judge = Sentigent(profile="financial_ops")

    # Option 1: Decorator
    @wrap_node(judge)
    def process_refund(state):
        ...

    # Option 2: Node class
    node = SentigentNode(judge, process_refund)
    graph.add_node("process_refund", node)
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from sentigent.core.engine import Sentigent
from sentigent.core.types import DecisionAction

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def wrap_node(
    judge: Sentigent,
    task_extractor: Callable[[dict[str, Any]], str] | None = None,
    context_extractor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    on_escalate: Callable[[Any], dict[str, Any]] | None = None,
    on_enrich: Callable[[Any], dict[str, Any]] | None = None,
    record_outcomes: bool = False,
) -> Callable[[F], F]:
    """Decorator that wraps a LangGraph node with Sentigent judgment.

    The decorator intercepts the node execution, evaluates the action
    with Sentigent, and either lets it proceed or takes alternative action.

    Args:
        judge: Sentigent instance to use for evaluation
        task_extractor: Optional function to extract task description from state
        context_extractor: Optional function to extract context from state
        on_escalate: Optional handler for escalation (default: adds escalation to state)
        on_enrich: Optional handler for enrichment (default: adds enrichment request to state)
        record_outcomes: If True, auto-record success/failure outcomes. Defaults to False
            because a function returning without exception doesn't necessarily mean the
            decision was correct. Set to True only when node success = decision correctness.
            Failure outcomes (exceptions) are always recorded regardless.

    Returns:
        Decorated function that includes Sentigent judgment
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            # Extract task and context from state
            task = (
                task_extractor(state)
                if task_extractor
                else _default_task_extractor(state, func.__name__)
            )
            context = (
                context_extractor(state)
                if context_extractor
                else _default_context_extractor(state)
            )
            agent_state = _extract_agent_state(state)

            # Evaluate with Sentigent
            decision = judge.evaluate(
                task=task,
                context=context,
                agent_state=agent_state,
            )

            logger.info(
                "Sentigent decision for '%s': %s (signals: %s)",
                func.__name__,
                decision.action.value,
                decision.signals,
            )

            # Build sentigent data as a new dict — never mutate state in-place.
            # LangGraph expects nodes to return new state via the reducer pattern.
            sentigent_data = {
                "_sentigent": {
                    "trace_id": decision.trace_id,
                    "action": decision.action.value,
                    "signals": decision.signals,
                    "reason": decision.reason,
                    "judgment_score": decision.judgment_score,
                }
            }

            # Act on decision
            if decision.action == DecisionAction.PROCEED:
                result = _safe_call(func, state, decision, judge, args, kwargs, record_outcomes)
                if isinstance(result, dict):
                    result.update(sentigent_data)
                    return result
                return sentigent_data

            elif decision.action == DecisionAction.SLOW_DOWN:
                sentigent_data["_sentigent"]["requires_validation"] = True
                result = _safe_call(func, state, decision, judge, args, kwargs, record_outcomes)
                if isinstance(result, dict):
                    result.update(sentigent_data)
                    return result
                return sentigent_data

            elif decision.action == DecisionAction.ENRICH:
                if on_enrich:
                    result = on_enrich(state)
                    if isinstance(result, dict):
                        result.update(sentigent_data)
                        return result
                sentigent_data["_sentigent"]["needs_enrichment"] = True
                sentigent_data["_sentigent"]["enrichment_reason"] = decision.reason
                return sentigent_data

            elif decision.action == DecisionAction.ESCALATE:
                if on_escalate:
                    result = on_escalate(state)
                    if isinstance(result, dict):
                        result.update(sentigent_data)
                        return result
                sentigent_data["_sentigent"]["escalated"] = True
                sentigent_data["_sentigent"]["escalation_reason"] = decision.reason
                return sentigent_data

            result = _safe_call(func, state, decision, judge, args, kwargs, record_outcomes)
            if isinstance(result, dict):
                result.update(sentigent_data)
                return result
            return sentigent_data

        return wrapper  # type: ignore
    return decorator


def _safe_call(
    func: Callable[..., Any],
    state: dict[str, Any],
    decision: Any,
    judge: Sentigent,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    record_outcomes: bool = False,
) -> Any:
    """Call the wrapped function with try/except to record outcomes (MOD 3.5).

    Args:
        record_outcomes: If True, records success ("correct") on return.
            Failure ("incorrect") is ALWAYS recorded on exception regardless
            of this flag, since an exception is an unambiguous bad outcome.
    """
    try:
        result = func(state, *args, **kwargs)
        # Record success outcome only if opted in — a function returning without
        # exception doesn't necessarily mean the decision was correct.
        if record_outcomes and decision.trace_id:
            try:
                judge.record_outcome(
                    decision.trace_id,
                    "correct",
                    f"Node {func.__name__} executed successfully",
                )
            except Exception:
                logger.debug("Failed to record success outcome for trace %s", decision.trace_id)
        return result
    except Exception:
        # Always record failure — an exception is an unambiguous bad outcome
        if decision.trace_id:
            try:
                judge.record_outcome(
                    decision.trace_id,
                    "incorrect",
                    f"Node {func.__name__} raised an exception",
                )
            except Exception:
                logger.debug("Failed to record failure outcome for trace %s", decision.trace_id)
        raise


class SentigentNode:
    """A LangGraph node class with built-in Sentigent judgment.

    Can be used directly as a node in a LangGraph StateGraph:

        node = SentigentNode(judge, process_refund)
        graph.add_node("process_refund", node)
    """

    def __init__(
        self,
        judge: Sentigent,
        func: Callable[[dict[str, Any]], dict[str, Any]],
        task_extractor: Callable[[dict[str, Any]], str] | None = None,
        context_extractor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        on_escalate: Callable[[Any], dict[str, Any]] | None = None,
        on_enrich: Callable[[Any], dict[str, Any]] | None = None,
        record_outcomes: bool = False,
    ) -> None:
        self.judge = judge
        self.func = func
        self.task_extractor = task_extractor
        self.context_extractor = context_extractor
        self.on_escalate = on_escalate
        self.on_enrich = on_enrich

        # Wrap the function
        self._wrapped = wrap_node(
            judge=judge,
            task_extractor=task_extractor,
            context_extractor=context_extractor,
            on_escalate=on_escalate,
            on_enrich=on_enrich,
            record_outcomes=record_outcomes,
        )(func)

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._wrapped(state)


def _default_task_extractor(state: dict[str, Any], node_name: str) -> str:
    """Extract a task description from LangGraph state."""
    # Try common state keys
    for key in ("task", "current_task", "objective", "query", "input"):
        if key in state and isinstance(state[key], str):
            return state[key]

    # Try messages (common in chat-based agents)
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            return last_msg.get("content", node_name)
        if isinstance(last_msg, str):
            return last_msg

    return f"Execute node: {node_name}"


def _default_context_extractor(state: dict[str, Any]) -> dict[str, Any]:
    """Extract evaluation context from LangGraph state."""
    context: dict[str, Any] = {}

    # Extract numeric values that could be evaluated against baselines
    for key, value in state.items():
        if key.startswith("_"):
            continue
        if isinstance(value, (int, float)):
            context[key] = value
        elif isinstance(value, str) and len(value) < 200:
            context[key] = value

    return context


def _extract_agent_state(state: dict[str, Any]) -> dict[str, Any]:
    """Extract agent state information from LangGraph state."""
    agent_state: dict[str, Any] = {}

    # Common agent state fields
    for key in ("step", "confidence", "retry_count", "iteration", "is_escalation"):
        if key in state:
            agent_state[key] = state[key]

    # Check for tool call information
    if "tool_calls" in state:
        agent_state["pending_tool_calls"] = len(state["tool_calls"])

    return agent_state
