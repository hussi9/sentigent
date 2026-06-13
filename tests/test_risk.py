"""RiskAssessor / PolicyWall — the deterministic hard-rule safety floor of fly mode (D3/F3).

Covers the hard rules fire, normal text is low-risk, AND the policy_wall stickiness invariant
(D-020): if ANY hard rule matches, the verdict carries policy_wall=True regardless of which rule
wins the score. The safety floor had no tests before this — itself a gap for an inviolable guard.
"""
from __future__ import annotations

import re
from unittest import mock

import pytest

from sentigent.operator import risk
from sentigent.operator.risk import RiskAssessor, RiskScore


@pytest.fixture
def a():
    return RiskAssessor()


@pytest.mark.parametrize("text,category", [
    ("git push --force origin main", "force_push"),
    ("git push -f", "force_push"),
    ("supabase db push", "prod_db"),
    ("DROP TABLE users", "prod_db"),
    ("rm -rf build/", "delete"),
    ("rotate the SERVICE_ROLE key", "secrets"),
    ("send the launch announcement email to all subscribers", "external_send"),
])
def test_hard_rules_trip_policy_wall(a, text, category):
    r = a.assess(text)
    assert r.policy_wall is True
    assert r.category == category
    assert r.level == "critical"
    assert r.reasons


@pytest.mark.parametrize("text", [
    "update the README copy",
    "rename a local variable",
    "add a unit test for the parser",
])
def test_routine_changes_are_low_and_no_wall(a, text):
    r = a.assess(text)
    assert r.policy_wall is False
    assert r.level in ("low", "medium")


def test_non_wall_rules_do_not_trip_the_wall(a):
    assert a.assess("npm install lodash").policy_wall is False     # install 0.3
    assert a.assess("run the alter table migration").policy_wall is False  # schema change 0.65
    assert a.assess("vercel --prod").policy_wall is False          # deploy 0.7, non-wall


def test_empty_text_is_zero_risk(a):
    r = a.assess("")
    assert r.score == 0.0 and r.policy_wall is False


def test_highest_base_wins_category_but_wall_preserved(a):
    # force-push (0.95 wall) co-occurs with a recursive delete (0.8 wall): highest base wins
    # category, and the wall obviously holds.
    r = a.assess("git push --force origin main && rm -rf node_modules")
    assert r.category == "force_push"
    assert r.policy_wall is True


def test_policy_wall_is_sticky_under_a_future_high_base_non_wall_rule():
    """Regression for the latent landmine (D-020): the OLD code carried the wall flag on whichever
    rule had the highest base, so a future high-base NON-wall rule co-occurring with a lower-base
    HARD rule would have silently dropped the hard-rule escalation. policy_wall must be sticky."""
    future_rules = list(risk._RULES) + [
        (re.compile(r"deploy-to-prod", re.I), "deploy", 0.92, False, "prod deploy (non-wall)"),
    ]
    with mock.patch.object(risk, "_RULES", future_rules):
        # 'deploy-to-prod' (0.92, non-wall) wins score; 'api_key' (0.75, WALL) must still trip it.
        r = RiskAssessor().assess("deploy-to-prod after rotating the api_key")
        assert r.score == pytest.approx(0.92)
        assert r.category == "deploy"       # highest base wins the headline category
        assert r.policy_wall is True        # ...but the hard rule is NOT lost
        assert any("credential" in x or "secret" in x.lower() for x in r.reasons)
