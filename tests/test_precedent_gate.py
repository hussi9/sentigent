"""Precedent gate — human decision_events drive verdicts before the signal ladder.

Regression guard for the 2026-07-07 principal review finding: the signal gate
almost always returns PROCEED on live tool calls, while the genuinely honest
signal (decision_events recording human approve/reject/correct/revert) never
influenced verdicts. This gate closes that loop.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

import pytest

from sentigent import Sentigent
from sentigent.core.precedents import PrecedentGate, normalize_signature
from sentigent.core.types import DecisionAction
from sentigent.memory.store import MemoryStore


# ── signature normalization ──────────────────────────────────────────────────

def test_normalize_bash_keeps_action_and_force_flag():
    assert normalize_signature("Bash", "git push --force origin main") == "bash:git push --force"
    assert normalize_signature("Bash", "git push origin main") == "bash:git push"


def test_normalize_bash_truncates_compound_command():
    assert normalize_signature("Bash", "rm -rf ./dist && echo ok") == "bash:rm -rf"


def test_normalize_sensitive_file_buckets():
    assert normalize_signature("Edit", "/repo/src/.env.production") == "edit:.env"
    assert normalize_signature("Write", "/etc/ssl/server.pem") == "write:.pem"


def test_normalize_plain_file_suffix():
    assert normalize_signature("Write", "/repo/a/b/config.yaml") == "write:.yaml"


# ── gate lookup ──────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="t-prec", org_id="t", db_path=str(tmp_path / "m.db"))


def _seed_reaction(store, kind, tool_name, tool_input, source="bash_revert"):
    """Write an ORIGINAL-action episode + a human reaction that references it via
    prior_trace_id — the real shape the gate reads. The reaction escalates/etc
    the ORIGINAL action's signature, not its own text."""
    trace_id = str(uuid.uuid4())
    conn = sqlite3.connect(store.db_path)
    try:
        conn.execute(
            """INSERT INTO episodes
               (trace_id, agent_id, org_id, timestamp, task, context,
                agent_state, signals, decision, reason, outcome)
               VALUES (?, ?, ?, '2026-07-07T00:00:00+00:00', ?, ?, '{}', '{}',
                       'proceed', '', NULL)""",
            (trace_id, store.agent_id, store.org_id,
             f"{tool_name}: {tool_input}",
             json.dumps({"tool_name": tool_name, "tool_input": tool_input})),
        )
        conn.commit()
    finally:
        conn.close()
    store.insert_decision_event({
        "agent_id": store.agent_id, "org_id": store.org_id, "ts": time.time(),
        "kind": kind, "domain": "global", "signal": "reaction",
        "target": "", "prior_trace_id": trace_id, "source": source,
        "confidence": 0.9, "meta": "{}",
    })


def test_gate_escalates_the_reverted_action_not_the_revert(store):
    # 3 reverts of a `git push --force` action → gate escalates that ACTION's
    # signature when about to repeat it (NOT the revert command itself).
    for _ in range(3):
        _seed_reaction(store, "revert", "Bash", "git push --force origin main")
    v = PrecedentGate(store).lookup("bash:git push --force")
    assert v is not None
    assert v.action == "escalate"
    assert v.sample_size == 3
    assert v.agreement == pytest.approx(1.0)


def test_gate_maps_approve_to_proceed_and_correct_to_slow_down(store):
    # These branches were dead before the prior_trace_id fix (prompt reactions
    # carry no target). Now they contribute.
    for _ in range(3):
        _seed_reaction(store, "approve", "Bash", "npm test", source="prompt_reaction")
    for _ in range(3):
        _seed_reaction(store, "correct", "Edit", "/repo/src/config.yaml", source="prompt_reaction")
    assert PrecedentGate(store).lookup("bash:npm test").action == "proceed"
    assert PrecedentGate(store).lookup("edit:.yaml").action == "slow_down"


def test_gate_returns_none_below_min_samples(store):
    _seed_reaction(store, "revert", "Bash", "git push --force origin main")
    _seed_reaction(store, "revert", "Bash", "git push --force origin main")
    assert PrecedentGate(store).lookup("bash:git push --force") is None


def test_gate_returns_none_for_unseen_signature(store):
    for _ in range(5):
        _seed_reaction(store, "revert", "Bash", "git push --force origin main")
    assert PrecedentGate(store).lookup("bash:ls") is None


def test_gate_ignores_reactions_with_no_prior_trace(store):
    # A reaction with no prior_trace_id can't be resolved to a judged action.
    for _ in range(4):
        store.insert_decision_event({
            "agent_id": store.agent_id, "org_id": store.org_id, "ts": time.time(),
            "kind": "approve", "domain": "global", "signal": "looks good ship it",
            "target": "", "prior_trace_id": "", "source": "prompt_reaction",
            "confidence": 0.7, "meta": "{}",
        })
    assert PrecedentGate(store)._events_by_signature() == {}


# ── engine wiring ────────────────────────────────────────────────────────────

def test_evaluate_uses_precedent_over_signal_ladder(tmp_db_path):
    judge = Sentigent(profile="default", agent_id="t-prec-eng", db_path=tmp_db_path)
    for _ in range(3):
        _seed_reaction(judge._memory, "revert", "Bash", "git push --force origin main")
    decision = judge.evaluate(
        task="push my branch",
        context={"tool_name": "Bash", "tool_input": "git push --force origin main"},
    )
    assert decision.action == DecisionAction.ESCALATE
    assert "precedent" in decision.reason.lower()
    assert decision.metadata.get("source") == "precedent"


def test_evaluate_no_precedent_falls_through_to_signals(tmp_db_path):
    judge = Sentigent(profile="default", agent_id="t-prec-eng2", db_path=tmp_db_path)
    decision = judge.evaluate(
        task="list files",
        context={"tool_name": "Bash", "tool_input": "ls -la"},
    )
    # No precedent recorded -> normal signal path -> proceed, no precedent source.
    assert decision.metadata.get("source") != "precedent"
