"""Profile registry — manages available domain profiles.

Profiles provide day-1 baselines (starter intuition) that get progressively
replaced by learned judgment as the agent accumulates operational experience.
"""

from __future__ import annotations

from typing import Callable

from sentigent.core.types import Profile, ValueHierarchy, WorldModel
from sentigent.profiles.financial_ops import create_financial_ops_profile
from sentigent.profiles.customer_support import create_customer_support_profile
from sentigent.profiles.code_review import create_code_review_profile

# Registry of all available profiles
_PROFILE_REGISTRY: dict[str, Callable[[], Profile]] = {
    "financial_ops": create_financial_ops_profile,
    "customer_support": create_customer_support_profile,
    "code_review": create_code_review_profile,
}


def get_profile(name: str) -> Profile:
    """Get a profile by name.

    Args:
        name: Profile name (e.g., "financial_ops", "customer_support")

    Returns:
        Profile object with default baselines and value hierarchy

    Raises:
        ValueError: If profile name is not found
    """
    if name == "default":
        return _create_default_profile()

    creator = _PROFILE_REGISTRY.get(name)
    if creator is None:
        available = ", ".join(sorted(_PROFILE_REGISTRY.keys()))
        raise ValueError(
            f"Unknown profile: '{name}'. Available profiles: {available}"
        )
    return creator()


def register_profile(name: str, creator: Callable[[], Profile]) -> None:
    """Register a custom profile.

    Args:
        name: Profile name
        creator: Callable that returns a Profile object
    """
    _PROFILE_REGISTRY[name] = creator


def list_profiles() -> list[str]:
    """List all available profile names."""
    return sorted(_PROFILE_REGISTRY.keys())


def _create_default_profile() -> Profile:
    """Create a minimal default profile with conservative settings."""
    return Profile(
        name="default",
        description="Minimal default profile with conservative settings",
        values=ValueHierarchy(
            values=[
                ("safety", 1.0),
                ("accuracy", 0.8),
                ("speed", 0.5),
            ]
        ),
        world_model=WorldModel(baselines={}),
    )
