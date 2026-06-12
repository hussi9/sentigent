"""Shared test fixtures for Sentigent test suite.

Provides tmp_path-based database fixtures that don't use os.remove() (LOW 4.9).
Pytest's tmp_path is cleaned up automatically after the test session.
"""

import os
import pathlib

import pytest

# ── Load .env once for the entire test session ────────────────────────────────
# This makes SUPABASE_* and SENTIGENT_* available to integration tests
_env_file = pathlib.Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k, _v = _k.strip(), _v.strip().strip("\"'")
            if _k.startswith(("SUPABASE_", "SENTIGENT_")):
                os.environ.setdefault(_k, _v)

from sentigent import Sentigent
from sentigent.core.types import Profile, ValueHierarchy, WorldModel


@pytest.fixture
def tmp_db_path(tmp_path):
    """Provide a temporary database path that gets cleaned up automatically."""
    return str(tmp_path / "test_sentigent.db")


@pytest.fixture
def tmp_judge(tmp_db_path):
    """Create a Sentigent instance with a pytest-managed temp database."""
    return Sentigent(
        profile="financial_ops",
        agent_id="test_agent",
        db_path=tmp_db_path,
    )


@pytest.fixture
def safety_profile() -> Profile:
    """Profile that prioritizes safety over speed."""
    return Profile(
        name="test_safety",
        values=ValueHierarchy(values=[
            ("financial_safety", 1.0),
            ("safety", 1.0),
            ("speed", 0.3),
        ]),
        world_model=WorldModel(baselines={}),
        signal_thresholds={
            "caution_threshold": 2.0,
            "doubt_threshold": 0.6,
            "urgency_threshold": 0.8,
            "confidence_fast_path": 0.9,
            "frustration_retries": 3,
        },
    )


@pytest.fixture
def speed_profile() -> Profile:
    """Profile that prioritizes speed over safety."""
    return Profile(
        name="test_speed",
        values=ValueHierarchy(values=[
            ("speed", 1.0),
            ("safety", 0.3),
        ]),
        world_model=WorldModel(baselines={}),
    )
