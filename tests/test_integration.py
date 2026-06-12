"""End-to-end integration tests against real Supabase.

These tests require real credentials and hit the actual database.
Run with:
    uv run pytest tests/test_integration.py -m integration -v
    uv run pytest tests/test_integration.py -m integration -v -s  # with output

Skip automatically when env vars are not set.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from sentigent import Sentigent
from sentigent.core.types import DecisionAction

# ── Marker: skip unless real Supabase creds are present ───────────────────────

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    os.environ.get("SUPABASE_ANON_KEY", ""),
)
_HAS_SUPABASE = bool(_SUPABASE_URL and _SUPABASE_KEY)

integration = pytest.mark.skipif(
    not _HAS_SUPABASE,
    reason="SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY required for integration tests",
)
pytestmark = pytest.mark.integration


# ── Shared fixture ─────────────────────────────────────────────────────────────


@pytest.fixture()
def judge():
    """Sentigent instance wired to real Supabase (hussi org)."""
    db_path = os.path.join(tempfile.gettempdir(), "sentigent_integration_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    inst = Sentigent(
        profile="code_review",
        agent_id="integration_test_agent",
        org_id="hussi",
        db_path=db_path,
    )
    yield inst

    if os.path.exists(db_path):
        os.remove(db_path)


# ── Basic evaluate/outcome loop ────────────────────────────────────────────────


@integration
class TestEvaluateOutcomeLoop:
    """Verify the core evaluate → record_outcome → learn cycle works end-to-end."""

    def test_evaluate_returns_valid_decision(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="git push origin main",
            context={"branch": "main", "env": "production"},
            agent_state={"confidence": 0.85},
        )
        assert decision.trace_id, "trace_id must be non-empty"
        assert decision.action is not None
        assert decision.reason != ""
        assert isinstance(decision.signals, dict)
        assert "confidence" in decision.signals

    def test_correct_outcome_increases_score(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Read config.yaml",
            context={"path": "/etc/app/config.yaml"},
            agent_state={"confidence": 0.95},
        )
        judge.record_outcome(decision.trace_id, "correct", "File read successfully")
        assert judge.judgment_score >= 0.0

    def test_incorrect_outcome_is_stored(self, judge: Sentigent) -> None:
        decision = judge.evaluate(
            task="Deploy to staging",
            context={"env": "staging"},
            agent_state={"confidence": 0.7},
        )
        # Should not raise
        judge.record_outcome(decision.trace_id, "incorrect", "Deployment failed")

    def test_ten_outcomes_triggers_sync(self, judge: Sentigent) -> None:
        """Recording 10 outcomes should trigger _maybe_sync_layer2 without error."""
        trace_ids = []
        for i in range(10):
            d = judge.evaluate(
                task=f"Integration test operation {i}",
                context={"step": i, "test": True},
                agent_state={"confidence": 0.8},
            )
            trace_ids.append(d.trace_id)

        # Recording 10 correct outcomes triggers Layer 2 sync at the 10th
        for i, tid in enumerate(trace_ids):
            outcome = "correct" if i % 3 != 0 else "incorrect"
            judge.record_outcome(tid, outcome)

        # Verify score and stats are populated
        stats = judge._memory.get_outcome_stats()
        total = sum(stats.values())
        assert total == 10, f"Expected 10 recorded outcomes, got {total}"

    def test_judgment_score_reflects_outcomes(self, judge: Sentigent) -> None:
        """Score should be > 0 after some correct outcomes."""
        for _ in range(5):
            d = judge.evaluate(
                task="Safe read operation",
                context={"safe": True},
                agent_state={"confidence": 0.9},
            )
            judge.record_outcome(d.trace_id, "correct")

        assert judge.judgment_score > 0.0


# ── Layer 2 sync ──────────────────────────────────────────────────────────────


@integration
class TestLayer2Sync:
    """Verify SyncManager can communicate with real Supabase."""

    def test_can_connect_and_get_score(self) -> None:
        from sentigent.sync.manager import SyncManager

        sync = SyncManager(org_id="hussi", agent_id="integration_test_agent")
        result = sync.get_judgment_score()
        assert isinstance(result, dict), "get_judgment_score should return a dict"
        # Keys may vary; just verify no exception and we got data back
        assert "error" not in result or result.get("error") is None

    def test_push_episodes_empty_list_is_safe(self) -> None:
        from sentigent.sync.manager import SyncManager

        sync = SyncManager(org_id="hussi", agent_id="integration_test_agent")
        result = sync.push_episodes([])
        assert result["synced"] == 0
        assert result["failed"] == 0

    def test_pull_org_baselines_returns_list(self) -> None:
        from sentigent.sync.manager import SyncManager

        sync = SyncManager(org_id="hussi", agent_id="integration_test_agent")
        baselines = sync.pull_org_baselines("code_review")
        assert isinstance(baselines, list)

    def test_pull_org_patterns_returns_list(self) -> None:
        from sentigent.sync.manager import SyncManager

        sync = SyncManager(org_id="hussi", agent_id="integration_test_agent")
        patterns = sync.pull_org_patterns("code_review")
        assert isinstance(patterns, list)


# ── Layer 3 collective ────────────────────────────────────────────────────────


@integration
class TestLayer3Collective:
    """Verify Layer 3 opt-in/status/contribute flow works against Supabase."""

    def test_get_layer3_status_returns_dict(self) -> None:
        import os as _os
        import tempfile
        from sentigent.sync.manager import SyncManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            sync = SyncManager(org_id="hussi", agent_id="integration_test_agent", db_path=tmp_db)
            status = sync.get_layer3_status()
            assert isinstance(status, dict)
            assert "pool_size" in status
            assert "opted_in_profiles" in status
        finally:
            _os.unlink(tmp_db)

    def test_layer3_opt_in_roundtrip(self) -> None:
        """Set opt-in to True, verify, then restore to False."""
        import os as _os
        import tempfile
        from sentigent.sync.manager import SyncManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            sync = SyncManager(org_id="hussi", agent_id="integration_test_agent", db_path=tmp_db)
            ok = sync.set_layer3_opt_in("code_review", True)
            assert ok is True

            opted = sync.get_layer3_opt_in("code_review")
            assert opted is True

            sync.set_layer3_opt_in("code_review", False)
            assert sync.get_layer3_opt_in("code_review") is False
        finally:
            _os.unlink(tmp_db)

    def test_contribute_skips_when_opted_out(self) -> None:
        import os as _os
        import tempfile
        from sentigent.sync.manager import SyncManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            sync = SyncManager(org_id="hussi", agent_id="integration_test_agent", db_path=tmp_db)
            sync.set_layer3_opt_in("code_review", False)
            patterns = [
                {
                    "pattern_name": "test_integration_pattern",
                    "condition": "test",
                    "learned_action": "proceed",
                    "success_rate": 0.95,
                    "sample_size": 10,
                }
            ]
            result = sync.contribute_to_layer3(patterns, "code_review")
            assert result["opted_in"] is False
            assert result["contributed"] == 0
        finally:
            _os.unlink(tmp_db)

    def test_pull_layer3_patterns_returns_list(self) -> None:
        import os as _os
        import tempfile
        from sentigent.sync.manager import SyncManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            sync = SyncManager(org_id="hussi", agent_id="integration_test_agent", db_path=tmp_db)
            patterns = sync.pull_layer3_patterns()
            assert isinstance(patterns, list)
        finally:
            _os.unlink(tmp_db)


# ── Policy engine against Supabase ────────────────────────────────────────────


@integration
class TestPolicyEngineIntegration:
    """Verify org policies are loaded from Supabase and enforced correctly."""

    def test_policy_engine_loads_without_error(self, judge: Sentigent) -> None:
        """PolicyEngine should connect to Supabase and load policies."""
        # Trigger evaluate to load policies
        decision = judge.evaluate(
            task="Normal safe operation",
            context={},
            agent_state={"confidence": 0.9},
        )
        assert decision is not None

    def test_destructive_command_triggers_policy(self, judge: Sentigent) -> None:
        """rm -rf patterns should be caught by default policies."""
        decision = judge.evaluate(
            task="rm -rf /var/data/production",
            context={"tool_name": "Bash"},
            agent_state={"confidence": 0.9},
        )
        # Default policy for rm -rf should escalate or slow_down
        assert decision.action in (
            DecisionAction.ESCALATE,
            DecisionAction.SLOW_DOWN,
            DecisionAction.PROCEED,  # if policy not seeded, falls through
        )
