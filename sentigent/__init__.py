"""
Sentigent — The judgment layer that learns.

Self-learning operational intuition for AI agents.
"""

from sentigent.config import SentigentConfig, get_config
from sentigent.core.engine import Sentigent
from sentigent.core.types import (
    BaselineStats,
    Decision,
    DecisionAction,
    Profile,
    Signal,
    SignalType,
    Trace,
    ValueHierarchy,
    WorldModel,
)

__version__ = "0.1.0"

__all__ = [
    "Sentigent",
    "SentigentConfig",
    "get_config",
    "BaselineStats",
    "Decision",
    "DecisionAction",
    "Profile",
    "Signal",
    "SignalType",
    "Trace",
    "ValueHierarchy",
    "WorldModel",
    # Lazy-loaded (see __getattr__ below)
    "AsyncSentigent",
    "judge_call",
    "JudgmentContext",
    "EscalationRequired",
    "SentigentEvent",
    "EventBus",
    "get_event_bus",
]


# PEP 562 — Module-level __getattr__ for lazy imports.
# Avoids importing asyncio and integrations at module import time
# while preserving isinstance() checks and type safety.
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AsyncSentigent": ("sentigent.core.async_engine", "AsyncSentigent"),
    "judge_call": ("sentigent.integrations.universal", "judge_call"),
    "JudgmentContext": ("sentigent.integrations.universal", "JudgmentContext"),
    "EscalationRequired": ("sentigent.integrations.universal", "EscalationRequired"),
    "SentigentEvent": ("sentigent.events", "SentigentEvent"),
    "EventBus": ("sentigent.events", "EventBus"),
    "get_event_bus": ("sentigent.events", "get_event_bus"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        # Cache in module namespace for subsequent access
        globals()[name] = value
        return value
    raise AttributeError(f"module 'sentigent' has no attribute {name!r}")
