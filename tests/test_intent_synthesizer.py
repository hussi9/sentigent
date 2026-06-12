"""Tests for IntentSynthesizer and SentigentIntentBlock."""
from __future__ import annotations
import sqlite3
import pytest
from sentigent.core.intent_synthesizer import IntentSynthesizer, SentigentIntentBlock


def _make_store(tmp_path):
    from sentigent.memory.store import MemoryStore
    return MemoryStore(
        agent_id="test_agent",
        org_id="test_org",
        db_path=str(tmp_path / "test.db"),
    )


class TestSentigentIntentBlock:
    def test_to_context_block_contains_objective(self):
        block = SentigentIntentBlock(
            objective="Fix JWT auth bug",
            constraints=[],
            relevant_history=[],
            recommended_skill="debugger",
            recommended_model="sonnet",
            routing_confidence=0.82,
            success_signals=["tests pass"],
            cold_start=False,
        )
        text = block.to_context_block()
        assert "SENTIGENT_INTENT" in text
        assert "Fix JWT auth bug" in text
        assert "debugger" in text
        assert "0.82" in text

    def test_to_context_block_cold_start_note(self):
        block = SentigentIntentBlock(
            objective="Write a script",
            constraints=[],
            relevant_history=[],
            recommended_skill="",
            recommended_model="sonnet",
            routing_confidence=0.0,
            success_signals=[],
            cold_start=True,
        )
        assert "cold_start=true" in block.to_context_block()

    def test_to_context_block_includes_constraints(self):
        block = SentigentIntentBlock(
            objective="Deploy",
            constraints=["no_force_push → block", "protect_env → slow_down"],
            relevant_history=[],
            recommended_skill="",
            recommended_model="sonnet",
            routing_confidence=0.0,
            success_signals=[],
            cold_start=False,
        )
        text = block.to_context_block()
        assert "no_force_push" in text

    def test_to_dict_round_trips(self):
        block = SentigentIntentBlock(
            objective="goal",
            constraints=["c1"],
            relevant_history=[{"task": "t", "decision": "proceed", "outcome": "correct"}],
            recommended_skill="debugger",
            recommended_model="haiku",
            routing_confidence=0.75,
            success_signals=["passes"],
            cold_start=False,
        )
        d = block.to_dict()
        assert d["objective"] == "goal"
        assert d["routing_confidence"] == 0.75
        assert d["cold_start"] is False


class TestIntentSynthesizer:
    def test_synthesize_empty_store_returns_cold_start(self, tmp_path):
        store = _make_store(tmp_path)
        synth = IntentSynthesizer()
        block = synth.synthesize(task="fix the auth bug", store=store)
        assert isinstance(block, SentigentIntentBlock)
        assert block.cold_start is True
        assert "auth" in block.objective.lower() or "fix" in block.objective.lower()

    def test_synthesize_uses_similar_episodes(self, tmp_path):
        store = _make_store(tmp_path)
        # Seed 25 episodes so cold_start=False
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        for i in range(25):
            conn.execute(
                "INSERT INTO episodes (trace_id, agent_id, org_id, timestamp, task, "
                "context, agent_state, signals, decision, reason, outcome) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"t{i}", "test_agent", "test_org", f"2026-01-{i+1:02d}T00:00:00Z",
                 "fix authentication JWT expiry bug in auth module",
                 "{}", "{}", "{}", "proceed", "", "correct"),
            )
        conn.commit()
        conn.close()

        synth = IntentSynthesizer()
        block = synth.synthesize(task="fix JWT token expiry problem", store=store)
        assert block.cold_start is False
        assert len(block.relevant_history) > 0

    def test_synthesize_no_store_returns_defaults(self):
        synth = IntentSynthesizer()
        block = synth.synthesize(task="deploy to staging")
        assert isinstance(block, SentigentIntentBlock)
        assert block.cold_start is True
        assert block.recommended_model in ("sonnet", "haiku", "opus")

    def test_synthesize_extracts_goal_from_task(self, tmp_path):
        store = _make_store(tmp_path)
        synth = IntentSynthesizer()
        block = synth.synthesize(task="Fix the broken login form in auth/login.py", store=store)
        assert len(block.objective) > 0
        assert len(block.objective) <= 120
