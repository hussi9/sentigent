"""Tests for Layer 3 collective intelligence — SyncManager contribution/consumption."""
from __future__ import annotations

import sqlite3
import pytest


# ── Shared factory ─────────────────────────────────────────────────────────────

def _mgr(tmp_path):
    """Return a SyncManager backed by a fresh temp SQLite database."""
    from sentigent.sync.manager import SyncManager
    return SyncManager(
        org_id="test_org",
        agent_id="test_agent",
        db_path=str(tmp_path / "test.db"),
    )


def _opted_in_mgr(tmp_path, profile: str = "default"):
    """Return a manager that has already opted in for the given profile."""
    mgr = _mgr(tmp_path)
    mgr.set_layer3_opt_in(profile, True)
    return mgr


# ── set_layer3_opt_in ──────────────────────────────────────────────────────────

class TestSetLayer3OptIn:
    def test_opt_in_returns_true_and_persists(self, tmp_path):
        mgr = _mgr(tmp_path)
        ok = mgr.set_layer3_opt_in("security_engineer", True)
        assert ok is True
        assert mgr.get_layer3_opt_in("security_engineer") is True

    def test_opt_out_returns_true_and_persists(self, tmp_path):
        mgr = _mgr(tmp_path)
        mgr.set_layer3_opt_in("default", True)
        ok = mgr.set_layer3_opt_in("default", False)
        assert ok is True
        assert mgr.get_layer3_opt_in("default") is False

    def test_opt_in_then_opt_out_roundtrip(self, tmp_path):
        mgr = _mgr(tmp_path)
        mgr.set_layer3_opt_in("code_review", True)
        assert mgr.get_layer3_opt_in("code_review") is True
        mgr.set_layer3_opt_in("code_review", False)
        assert mgr.get_layer3_opt_in("code_review") is False

    def test_error_returns_false(self, tmp_path, monkeypatch):
        mgr = _mgr(tmp_path)
        monkeypatch.setattr(mgr, "_get_local_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
        assert mgr.set_layer3_opt_in("default", True) is False


# ── get_layer3_opt_in ──────────────────────────────────────────────────────────

class TestGetLayer3OptIn:
    def test_returns_true_when_opted_in(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path, "security_engineer")
        assert mgr.get_layer3_opt_in("security_engineer") is True

    def test_returns_false_when_no_record(self, tmp_path):
        mgr = _mgr(tmp_path)
        assert mgr.get_layer3_opt_in("security_engineer") is False

    def test_returns_false_when_opted_out(self, tmp_path):
        mgr = _mgr(tmp_path)
        mgr.set_layer3_opt_in("default", True)
        mgr.set_layer3_opt_in("default", False)
        assert mgr.get_layer3_opt_in("default") is False

    def test_exception_returns_false(self, tmp_path, monkeypatch):
        mgr = _mgr(tmp_path)
        monkeypatch.setattr(mgr, "_get_local_conn", lambda: (_ for _ in ()).throw(RuntimeError("network error")))
        assert mgr.get_layer3_opt_in("default") is False


# ── contribute_to_layer3 ───────────────────────────────────────────────────────

class TestContributeToLayer3:
    def test_skips_when_not_opted_in(self, tmp_path):
        mgr = _mgr(tmp_path)
        patterns = [{"pattern_name": "p1", "learned_action": "proceed",
                     "success_rate": 0.9, "sample_size": 10}]
        result = mgr.contribute_to_layer3(patterns, "default")
        assert result["opted_in"] is False
        assert result["contributed"] == 0
        assert result["skipped"] == 1

    def test_skips_low_success_rate(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        patterns = [{"pattern_name": "low_rate", "learned_action": "proceed",
                     "success_rate": 0.7, "sample_size": 10}]
        result = mgr.contribute_to_layer3(patterns, "default")
        assert result["skipped"] == 1
        assert result["contributed"] == 0

    def test_skips_small_sample(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        patterns = [{"pattern_name": "small_sample", "learned_action": "proceed",
                     "success_rate": 0.95, "sample_size": 3}]
        result = mgr.contribute_to_layer3(patterns, "default")
        assert result["skipped"] == 1
        assert result["contributed"] == 0

    def test_contributes_qualifying_pattern(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        patterns = [{"pattern_name": "good_pattern", "learned_action": "proceed",
                     "success_rate": 0.9, "sample_size": 20}]
        result = mgr.contribute_to_layer3(patterns, "default")
        assert result["contributed"] == 1
        assert result["skipped"] == 0
        assert result["opted_in"] is True

    def test_no_org_id_in_pulled_pattern(self, tmp_path):
        """Patterns pulled from the pool must not expose org_id."""
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3(
            [{"pattern_name": "anon_pattern", "learned_action": "slow_down",
              "success_rate": 0.92, "sample_size": 15}],
            "default",
        )
        pulled = mgr.pull_layer3_patterns()
        assert len(pulled) == 1
        assert "org_id" not in pulled[0]
        assert pulled[0]["pattern_name"] == "anon_pattern"
        assert pulled[0]["learned_action"] == "slow_down"

    def test_industry_tags_passed_through(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3(
            [{"pattern_name": "fin_pattern", "learned_action": "escalate",
              "success_rate": 0.88, "sample_size": 12}],
            "default",
            industry_tags=["fintech"],
        )
        pulled = mgr.pull_layer3_patterns()
        assert pulled[0]["industry_tags"] == ["fintech"]

    def test_multiple_patterns_mixed(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        patterns = [
            {"pattern_name": "good1", "learned_action": "proceed", "success_rate": 0.9, "sample_size": 20},
            {"pattern_name": "low_rate", "learned_action": "proceed", "success_rate": 0.6, "sample_size": 20},
            {"pattern_name": "good2", "learned_action": "slow_down", "success_rate": 0.88, "sample_size": 10},
            {"pattern_name": "tiny", "learned_action": "escalate", "success_rate": 0.95, "sample_size": 2},
        ]
        result = mgr.contribute_to_layer3(patterns, "default")
        assert result["contributed"] == 2
        assert result["skipped"] == 2

    def test_merges_existing_pattern(self, tmp_path):
        """Contributing the same pattern twice should merge via weighted average."""
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3(
            [{"pattern_name": "recurring", "learned_action": "proceed",
              "success_rate": 0.9, "sample_size": 10}],
            "default",
        )
        mgr.contribute_to_layer3(
            [{"pattern_name": "recurring", "learned_action": "proceed",
              "success_rate": 1.0, "sample_size": 10}],
            "default",
        )
        pulled = mgr.pull_layer3_patterns()
        assert len(pulled) == 1
        assert pulled[0]["sample_size"] == 20
        assert pulled[0]["contributing_org_count"] == 2
        assert abs(pulled[0]["success_rate"] - 0.95) < 0.01


# ── pull_layer3_patterns ───────────────────────────────────────────────────────

class TestPullLayer3Patterns:
    def test_returns_patterns_from_pool(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3([
            {"pattern_name": "p1", "learned_action": "proceed", "success_rate": 0.92, "sample_size": 100},
            {"pattern_name": "p2", "learned_action": "escalate", "success_rate": 0.88, "sample_size": 50},
        ], "default")
        patterns = mgr.pull_layer3_patterns()
        assert len(patterns) == 2
        assert patterns[0]["pattern_name"] == "p1"  # highest success_rate first

    def test_empty_pool_returns_empty_list(self, tmp_path):
        mgr = _mgr(tmp_path)
        assert mgr.pull_layer3_patterns() == []

    def test_exception_returns_empty_list(self, tmp_path, monkeypatch):
        mgr = _mgr(tmp_path)
        monkeypatch.setattr(mgr, "_get_local_conn", lambda: (_ for _ in ()).throw(RuntimeError("pool unavailable")))
        assert mgr.pull_layer3_patterns() == []

    def test_filters_by_min_success_rate(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3([
            {"pattern_name": "high", "learned_action": "block", "success_rate": 0.95, "sample_size": 20},
            {"pattern_name": "low", "learned_action": "proceed", "success_rate": 0.85, "sample_size": 20},
        ], "default")
        patterns = mgr.pull_layer3_patterns(min_success_rate=0.90)
        assert len(patterns) == 1
        assert patterns[0]["pattern_name"] == "high"

    def test_filters_by_industry_tags(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path)
        mgr.contribute_to_layer3(
            [{"pattern_name": "fin", "learned_action": "escalate", "success_rate": 0.9, "sample_size": 20}],
            "default", industry_tags=["fintech"],
        )
        mgr.contribute_to_layer3(
            [{"pattern_name": "health", "learned_action": "proceed", "success_rate": 0.9, "sample_size": 20}],
            "default", industry_tags=["healthcare"],
        )
        results = mgr.pull_layer3_patterns(industry_tags=["fintech"])
        assert len(results) == 1
        assert results[0]["pattern_name"] == "fin"


# ── get_layer3_status ──────────────────────────────────────────────────────────

class TestGetLayer3Status:
    def test_returns_status_with_opted_in_profiles(self, tmp_path):
        mgr = _opted_in_mgr(tmp_path, "security_engineer")
        mgr.contribute_to_layer3([
            {"pattern_name": "p1", "learned_action": "proceed", "success_rate": 0.9, "sample_size": 20},
            {"pattern_name": "p2", "learned_action": "escalate", "success_rate": 0.88, "sample_size": 50},
        ], "security_engineer")

        status = mgr.get_layer3_status()
        assert "pool_size" in status
        assert "opted_in_profiles" in status
        assert "security_engineer" in status["opted_in_profiles"]
        assert status["pool_size"] == 2

    def test_exception_returns_empty_status(self, tmp_path, monkeypatch):
        mgr = _mgr(tmp_path)
        monkeypatch.setattr(mgr, "_get_local_conn", lambda: (_ for _ in ()).throw(RuntimeError("network error")))
        status = mgr.get_layer3_status()
        assert status["opted_in_profiles"] == []
        assert status.get("pool_size", 0) == 0

    def test_empty_status_when_no_data(self, tmp_path):
        mgr = _mgr(tmp_path)
        status = mgr.get_layer3_status()
        assert status["opted_in_profiles"] == []
        assert status["pool_size"] == 0


# ── PatternMiner.get_patterns ──────────────────────────────────────────────────

class TestPatternMinerGetPatterns:
    def test_returns_empty_when_no_db(self, tmp_path):
        from sentigent.learning.pattern_miner import PatternMiner
        miner = PatternMiner(db_path=str(tmp_path / "nonexistent.db"))
        patterns = miner.get_patterns()
        assert patterns == []

    def test_returns_patterns_from_db(self, tmp_path):
        db = str(tmp_path / "test.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE procedural_rules (
                id INTEGER PRIMARY KEY,
                agent_id TEXT DEFAULT 'agent',
                pattern_name TEXT,
                condition TEXT DEFAULT '{}',
                learned_action TEXT,
                success_rate REAL,
                sample_size INTEGER,
                last_reinforced TEXT DEFAULT ''
            )
        """)
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('force_push_block', 'block', 0.95, 30)")
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('deploy_slow_down', 'slow_down', 0.75, 10)")
        conn.commit()
        conn.close()

        from sentigent.learning.pattern_miner import PatternMiner
        miner = PatternMiner(db_path=db)
        patterns = miner.get_patterns()
        assert len(patterns) == 2
        assert patterns[0].pattern_name == "force_push_block"

    def test_min_success_rate_filter(self, tmp_path):
        db = str(tmp_path / "test.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE procedural_rules (
                id INTEGER PRIMARY KEY,
                agent_id TEXT DEFAULT 'agent',
                pattern_name TEXT,
                condition TEXT DEFAULT '{}',
                learned_action TEXT,
                success_rate REAL,
                sample_size INTEGER,
                last_reinforced TEXT DEFAULT ''
            )
        """)
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('high', 'block', 0.95, 20)")
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('low', 'proceed', 0.6, 20)")
        conn.commit()
        conn.close()

        from sentigent.learning.pattern_miner import PatternMiner
        miner = PatternMiner(db_path=db)
        patterns = miner.get_patterns(min_success_rate=0.85)
        assert len(patterns) == 1
        assert patterns[0].pattern_name == "high"

    def test_min_samples_filter(self, tmp_path):
        db = str(tmp_path / "test.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE procedural_rules (
                id INTEGER PRIMARY KEY,
                agent_id TEXT DEFAULT 'agent',
                pattern_name TEXT,
                condition TEXT DEFAULT '{}',
                learned_action TEXT,
                success_rate REAL,
                sample_size INTEGER,
                last_reinforced TEXT DEFAULT ''
            )
        """)
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('many', 'block', 0.9, 50)")
        conn.execute("INSERT INTO procedural_rules (pattern_name, learned_action, success_rate, sample_size) VALUES ('few', 'block', 0.9, 2)")
        conn.commit()
        conn.close()

        from sentigent.learning.pattern_miner import PatternMiner
        miner = PatternMiner(db_path=db)
        patterns = miner.get_patterns(min_samples=5)
        assert len(patterns) == 1
        assert patterns[0].pattern_name == "many"
