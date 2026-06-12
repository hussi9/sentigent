"""Universal integration — framework-agnostic decorator and context manager.

Works with any Python framework: CrewAI, AutoGen, OpenAI Swarm, bare Python,
FastAPI endpoints, Flask routes, or any callable.

Usage:

    from sentigent import Sentigent
    from sentigent.integrations.universal import judge_call, JudgmentContext

    judge = Sentigent(profile="financial_ops")

    # Option 1: Decorator (simplest)
    @judge_call(judge, task="process refund")
    def process_refund(amount: float, customer_id: str) -> dict:
        ...

    # Option 2: Context manager (more control)
    with JudgmentContext(judge, task="process refund", context={"amount": 500}) as jctx:
        result = do_something()
        jctx.record_success()  # or jctx.record_failure("reason")

    # Option 3: Decorator with dynamic task/context extraction
    @judge_call(judge, task_from_arg="task", context_from_kwargs=True)
    def generic_action(task: str, **kwargs):
        ...
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from sentigent.core.engine import Sentigent
from sentigent.core.types import Decision, DecisionAction

logger = logging.getLogger("sentigent.integrations.universal")

F = TypeVar("F", bound=Callable[..., Any])


def judge_call(
    judge: Sentigent,
    task: str | None = None,
    task_from_arg: str | None = None,
    context: dict[str, Any] | None = None,
    context_from_kwargs: bool = False,
    agent_state: dict[str, Any] | None = None,
    on_escalate: Callable[[Decision], Any] | None = None,
    on_enrich: Callable[[Decision], Any] | None = None,
    record_outcomes: bool = True,
) -> Callable[[F], F]:
    """Universal decorator that wraps any function with Sentigent judgment.

    Evaluates before execution, records outcomes after. Works with any framework.

    Args:
        judge: Sentigent instance
        task: Static task description (or use task_from_arg)
        task_from_arg: Name of function argument to use as task description
        context: Static context dict (or use context_from_kwargs)
        context_from_kwargs: If True, extract numeric/string kwargs as context
        agent_state: Agent state dict to pass to evaluation
        on_escalate: Optional handler for escalation decisions
        on_enrich: Optional handler for enrichment decisions
        record_outcomes: If True, auto-record success/failure outcomes

    Returns:
        Decorated function with judgment layer
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Resolve task description
            resolved_task = task or f"Execute {func.__name__}"
            if task_from_arg and task_from_arg in kwargs:
                resolved_task = str(kwargs[task_from_arg])
            elif task_from_arg and args:
                # Try positional arg matching via function signature
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                if task_from_arg in param_names:
                    idx = param_names.index(task_from_arg)
                    if idx < len(args):
                        resolved_task = str(args[idx])

            # Resolve context
            resolved_context = dict(context) if context else {}
            if context_from_kwargs:
                for key, value in kwargs.items():
                    if isinstance(value, (int, float)):
                        resolved_context[key] = value
                    elif isinstance(value, str) and len(value) < 200:
                        resolved_context[key] = value

            # Evaluate
            decision = judge.evaluate(
                task=resolved_task,
                context=resolved_context,
                agent_state=agent_state or {},
            )

            logger.info(
                "Judgment for %s: %s (confidence=%.2f)",
                func.__name__, decision.action.value, decision.confidence,
            )

            # Handle non-proceed decisions
            if decision.action == DecisionAction.ESCALATE:
                if on_escalate:
                    return on_escalate(decision)
                raise EscalationRequired(decision)

            if decision.action == DecisionAction.ENRICH:
                if on_enrich:
                    return on_enrich(decision)
                # Fall through — enrich is advisory, still execute

            # Execute the function
            try:
                result = func(*args, **kwargs)
                if record_outcomes and decision.trace_id:
                    try:
                        judge.record_outcome(
                            decision.trace_id, "correct",
                            f"{func.__name__} executed successfully",
                        )
                    except Exception:
                        logger.debug("Failed to record success outcome")
                return result
            except Exception:
                if record_outcomes and decision.trace_id:
                    try:
                        judge.record_outcome(
                            decision.trace_id, "incorrect",
                            f"{func.__name__} raised an exception",
                        )
                    except Exception:
                        logger.debug("Failed to record failure outcome")
                raise

        return wrapper  # type: ignore
    return decorator


class EscalationRequired(Exception):
    """Raised when Sentigent decides an action requires human review.

    Catch this exception to handle escalations in your framework:

        try:
            process_refund(amount=50000)
        except EscalationRequired as e:
            notify_human(e.decision.reason)
    """

    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        super().__init__(
            f"Sentigent escalation required: {decision.reason} "
            f"(trace_id={decision.trace_id})"
        )


class JudgmentContext:
    """Context manager for wrapping arbitrary code blocks with Sentigent judgment.

    Provides more control than the decorator for complex workflows:

        with JudgmentContext(judge, task="batch process", context={"batch_size": 1000}) as jctx:
            if jctx.should_proceed:
                results = run_batch()
                jctx.record_success()
            elif jctx.should_enrich:
                # Get more context first
                extra = fetch_more_data()
                results = run_batch(extra=extra)
                jctx.record_success()
            else:
                jctx.record_failure("Escalated, not proceeding")
    """

    def __init__(
        self,
        judge: Sentigent,
        task: str,
        context: dict[str, Any] | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> None:
        self.judge = judge
        self.task = task
        self.context = context or {}
        self.agent_state = agent_state or {}
        self.decision: Decision | None = None
        self._outcome_recorded = False

    def __enter__(self) -> JudgmentContext:
        self.decision = self.judge.evaluate(
            task=self.task,
            context=self.context,
            agent_state=self.agent_state,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self.decision and not self._outcome_recorded:
            if exc_type is not None:
                self.record_failure(f"Exception: {exc_type.__name__}")
            # If no outcome recorded and no exception, leave as pending
            # (will be auto-attributed after absence window)

    @property
    def should_proceed(self) -> bool:
        """True if Sentigent recommends proceeding."""
        return self.decision is not None and self.decision.action in (
            DecisionAction.PROCEED, DecisionAction.SLOW_DOWN,
        )

    @property
    def should_enrich(self) -> bool:
        """True if Sentigent recommends gathering more context."""
        return self.decision is not None and self.decision.action == DecisionAction.ENRICH

    @property
    def should_escalate(self) -> bool:
        """True if Sentigent recommends human review."""
        return self.decision is not None and self.decision.action == DecisionAction.ESCALATE

    def record_success(self, feedback: str | None = None) -> None:
        """Record that the operation succeeded."""
        if self.decision and not self._outcome_recorded:
            try:
                self.judge.record_outcome(
                    self.decision.trace_id,
                    "correct",
                    feedback or "Recorded via JudgmentContext",
                )
            except Exception:
                logger.debug("Failed to record success outcome")
            self._outcome_recorded = True

    def record_failure(self, feedback: str | None = None) -> None:
        """Record that the operation failed."""
        if self.decision and not self._outcome_recorded:
            try:
                self.judge.record_outcome(
                    self.decision.trace_id,
                    "incorrect",
                    feedback or "Recorded via JudgmentContext",
                )
            except Exception:
                logger.debug("Failed to record failure outcome")
            self._outcome_recorded = True
