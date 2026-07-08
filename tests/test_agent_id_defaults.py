"""Regression tests: every "no explicit agent_id" code path must resolve to
sentigent.config's default (``default_agent``), never a hardcoded maintainer
name.

Context: the final whole-branch review (2026-07-08) found `agent_id="hussain"`
shipped as the fallback in claude-plugin/hooks/sentigent_hook.py,
sentigent/mcp_server.py, sentigent/cli.py, sentigent/core/coach.py, and
sentigent/core/prompt_observer.py. On a default install (no SENTIGENT_AGENT_ID
set), the PreToolUse/PostToolUse hook recorded episodes to
memory_hussain.db while `sentigent score`/`doctor`/the MCP tools resolved to
`memory_default_agent.db` via sentigent.config.get_config() — a split brain
where hook-recorded signal was invisible to every other surface. These tests
pin every one of those sites to config's agent_id so the split can't recur.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sentigent.config import get_config


@pytest.fixture(autouse=True)
def _no_agent_env(monkeypatch):
    """Every test in this file asserts the *unset-env* fallback path."""
    monkeypatch.delenv("SENTIGENT_AGENT_ID", raising=False)


def test_config_default_agent_id_is_not_a_person_name():
    """Sanity check the thing every other test in this file pins against."""
    assert get_config().agent_id == "default_agent"


# ─── claude-plugin/hooks/sentigent_hook.py ──────────────────────────────────

_hook_path = Path(__file__).parent.parent / "claude-plugin" / "hooks" / "sentigent_hook.py"
_spec = importlib.util.spec_from_file_location("sentigent_hook_agentdefaults", _hook_path)
sentigent_hook = importlib.util.module_from_spec(_spec)
sys.modules["sentigent_hook_agentdefaults"] = sentigent_hook
_spec.loader.exec_module(sentigent_hook)


def test_hook_get_judge_defaults_agent_id_to_config_default(monkeypatch):
    import sentigent.core.engine as engine_mod

    sentigent_hook._judge = None  # force _get_judge() to build a fresh one
    captured = {}

    class _FakeSentigent:
        def __init__(self, profile=None, agent_id=None):
            captured["agent_id"] = agent_id

    monkeypatch.setattr(engine_mod, "Sentigent", _FakeSentigent)
    try:
        sentigent_hook._get_judge()
        assert captured["agent_id"] == get_config().agent_id
    finally:
        sentigent_hook._judge = None  # don't leak the fake judge to other tests


# ─── sentigent/mcp_server.py ────────────────────────────────────────────────

def test_mcp_sentigent_coach_defaults_agent_id_to_config_default(monkeypatch):
    import sentigent.core.coach as coach_mod
    from sentigent import mcp_server

    captured = {}

    class _FakeCoach:
        def __init__(self, agent_id=None):
            captured["agent_id"] = agent_id

        def analyze(self, lookback_days=7):
            raise RuntimeError("stop before analysis — agent_id already captured")

    monkeypatch.setattr(coach_mod, "InteractionCoach", _FakeCoach)
    mcp_server.sentigent_coach()  # agent_id="" -> must resolve through config
    assert captured["agent_id"] == get_config().agent_id


def test_mcp_sentigent_prove_defaults_agent_id_to_config_default(monkeypatch):
    import sentigent.core.prove as prove_mod
    from sentigent import mcp_server

    captured = {}

    class _FakeProofEngine:
        def __init__(self, agent_id=None, org_id=None):
            captured["agent_id"] = agent_id

        def compute(self, days=90):
            raise RuntimeError("stop before compute — agent_id already captured")

    monkeypatch.setattr(prove_mod, "ProofEngine", _FakeProofEngine)
    mcp_server.sentigent_prove()  # agent_id="" -> must resolve through config
    assert captured["agent_id"] == get_config().agent_id


# ─── sentigent/core/coach.py + sentigent/core/prompt_observer.py ───────────

def test_interaction_coach_defaults_agent_id_to_config_default():
    from sentigent.core.coach import InteractionCoach

    coach = InteractionCoach()  # no agent_id passed
    assert coach.agent_id == get_config().agent_id


def test_prompt_observer_defaults_agent_id_to_config_default():
    from sentigent.core.prompt_observer import PromptObserver

    observer = PromptObserver()  # no agent_id passed
    assert observer.agent_id == get_config().agent_id


# ─── sentigent/cli.py ────────────────────────────────────────────────────────

def test_cli_coach_defaults_agent_id_to_config_default(capsys):
    from sentigent.cli import _cmd_coach

    with patch("sentigent.core.coach.InteractionCoach") as mock_coach_cls:
        mock_coach_cls.return_value.analyze.return_value.to_text.return_value = "report"
        _cmd_coach(agent_id="", days=7, as_json=False)
        _, kwargs = mock_coach_cls.call_args
        assert kwargs.get("agent_id") == get_config().agent_id
    out = capsys.readouterr().out
    assert get_config().agent_id in out


def test_cli_prompt_health_defaults_agent_id_to_config_default():
    from sentigent.cli import _cmd_prompt_health

    with patch("sentigent.core.prompt_observer.PromptObserver") as mock_obs_cls:
        mock_obs_cls.return_value.analyze.return_value.to_text.return_value = "report"
        _cmd_prompt_health(agent_id="", days=30, as_json=False)
        _, kwargs = mock_obs_cls.call_args
        assert kwargs.get("agent_id") == get_config().agent_id


def test_cli_prove_defaults_agent_id_to_config_default():
    from sentigent.cli import _cmd_prove

    with patch("sentigent.core.prove.ProofEngine") as mock_engine_cls:
        mock_engine_cls.return_value.compute.return_value.to_dict.return_value = {}
        _cmd_prove(agent_id="", days=90, as_json=True)
        _, kwargs = mock_engine_cls.call_args
        assert kwargs.get("agent_id") == get_config().agent_id


def test_cli_audit_defaults_agent_id_to_config_default(tmp_path, monkeypatch, capsys):
    from sentigent.cli import _cmd_audit

    monkeypatch.setenv("HOME", str(tmp_path))
    _cmd_audit(
        agent_id="",
        days=7,
        only_failures=False,
        only_patterns=False,
        by_tools=False,
    )
    out = capsys.readouterr().out
    assert f"agent '{get_config().agent_id}'" in out or f"agent: {get_config().agent_id}" in out
