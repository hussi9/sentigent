"""Closed-loop reconciler: skill-router follow/ignore → routing_seeds.outcome.

migrate_skill_router_data imports skill-router's routing DECISIONS as seeds.
This reconciler imports the downstream OUTCOME — whether each routed prompt
actually led to the announced skill being invoked — and writes it back to
routing_seeds.outcome by prompt_hash, the field routing.matcher already respects
(it excludes outcome='incorrect'). A route the human consistently ignores stops
firing; a route they follow is reinforced.

Conservative by design: a seed is demoted to 'incorrect' only when it was routed
>= MIN_OBSERVATIONS times and followed zero times, so thin/noisy signal can never
kill a good seed.
"""
from __future__ import annotations

import time

import pytest

from sentigent.memory.store import MemoryStore
from sentigent.routing import reconciler
from sentigent.routing.reconciler import (
    MIN_OBSERVATIONS,
    classify,
    parse_invocations,
    parse_route_events,
    preview,
    reconcile_outcomes,
)


# ── classify (the outcome policy) ────────────────────────────────────────────

def test_classify_single_follow_reinforces():
    assert classify(followed_count=1, total_count=1) == "correct"


def test_classify_thin_ignore_stays_neutral():
    # One route, never followed — not enough signal to demote a good seed.
    assert classify(followed_count=0, total_count=1) is None


def test_classify_repeated_ignore_demotes():
    assert classify(followed_count=0, total_count=2) == "incorrect"
    assert classify(followed_count=0, total_count=5) == "incorrect"


def test_classify_any_follow_beats_ignores():
    # A single genuine follow keeps the seed alive even amid ignores.
    assert classify(followed_count=1, total_count=3) == "correct"
    assert classify(followed_count=2, total_count=4) == "correct"


def test_min_observations_is_the_demote_floor():
    assert MIN_OBSERVATIONS >= 2  # never demote on a single data point


# ── log parsing (real event shapes) ──────────────────────────────────────────

def test_parse_route_events_keeps_only_embedding_route_with_hash_and_skill(tmp_path):
    log = tmp_path / "router.jsonl"
    log.write_text(
        '{"type":"embedding-route","ts":"2026-07-07T10:00:00","prompt_hash":"h1","skill":"test-runner"}\n'
        '{"type":"embedding-skip","ts":"2026-07-07T10:00:01","prompt_hash":"h2","skill":null}\n'
        '{"type":"chain-start","ts":"2026-07-07T10:00:02","steps":["x"],"name":"n"}\n'
        '{"type":"embedding-route","ts":"2026-07-07T10:00:03","prompt_hash":"h3"}\n'  # no skill → dropped
        'not json\n'
    )
    events = parse_route_events(log)
    assert [e["prompt_hash"] for e in events] == ["h1"]
    assert events[0]["skill"] == "test-runner"
    assert isinstance(events[0]["ts"], float)


def test_parse_invocations_handles_tab_and_space_formats(tmp_path):
    usage = tmp_path / "usage.log"
    usage.write_text(
        "2026-07-07 10:00:30\ttest-runner\n"        # modern TAB
        "2026-07-07 10:01:00 superpowers:brainstorming\n"  # legacy SPACE
        "garbage line\n"
    )
    invs = parse_invocations(usage)
    skills = {i["skill"] for i in invs}
    assert skills == {"test-runner", "superpowers:brainstorming"}


# ── end-to-end reconcile against a real store ────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return MemoryStore(agent_id="t-recon", org_id="t", db_path=str(tmp_path / "m.db"))


def _seed(store, prompt_hash, skill, emb=(1.0, 0.0, 0.0)):
    store.insert_routing_seed(
        prompt_hash=prompt_hash, prompt_text=f"prompt {prompt_hash}",
        task_type="operate", skill=skill, agent="general-purpose", model="sonnet",
        confidence=0.7, avg_sim=0.7, margin=0.1, neighbors=[], embedding=list(emb),
        outcome="neutral",
    )


def _outcome(store, prompt_hash):
    rows = store.get_all_routing_seeds_with_embeddings()
    return next(r["outcome"] for r in rows if r["prompt_hash"] == prompt_hash)


def test_reconcile_demotes_ignored_and_reinforces_followed(store):
    _seed(store, "ign", "refactor")     # will be routed twice, followed zero → demote
    _seed(store, "fol", "test-runner")  # routed once, followed → reinforce
    base = 1_800_000_000.0

    route_events = [
        {"prompt_hash": "ign", "skill": "refactor", "ts": base},
        {"prompt_hash": "ign", "skill": "refactor", "ts": base + 500},
        {"prompt_hash": "fol", "skill": "test-runner", "ts": base + 1000},
    ]
    invocations = [
        # test-runner invoked 30s after its route → followed
        {"skill": "test-runner", "ts": base + 1030},
        # nothing invokes 'refactor' → ignored
    ]

    stats = reconcile_outcomes(store, route_events, invocations)

    assert _outcome(store, "ign") == "incorrect"
    assert _outcome(store, "fol") == "correct"
    assert stats["demoted"] == 1
    assert stats["reinforced"] == 1


def test_reconcile_ignores_unknown_prompt_hashes(store):
    # A route event whose prompt_hash isn't a stored seed must not crash or write.
    stats = reconcile_outcomes(
        store,
        [{"prompt_hash": "ghost", "skill": "x", "ts": 1_800_000_000.0},
         {"prompt_hash": "ghost", "skill": "x", "ts": 1_800_000_100.0}],
        [],
    )
    assert stats["unknown"] == 1
    assert stats["demoted"] == 0


def test_reconcile_respects_follow_window(store):
    _seed(store, "late", "docs")
    base = 1_800_000_000.0
    stats = reconcile_outcomes(
        store,
        [{"prompt_hash": "late", "skill": "docs", "ts": base},
         {"prompt_hash": "late", "skill": "docs", "ts": base + 10}],
        # invocation is 10 minutes later — outside the 120s window → not a follow
        [{"skill": "docs", "ts": base + 600}],
    )
    assert _outcome(store, "late") == "incorrect"
    assert stats["demoted"] == 1


def test_preview_is_read_only_and_counts_verdicts():
    # preview never touches a store; it just tallies would-reinforce/would-demote.
    base = 1_800_000_000.0
    routes = [
        {"prompt_hash": "ign", "skill": "refactor", "ts": base},
        {"prompt_hash": "ign", "skill": "refactor", "ts": base + 500},
        {"prompt_hash": "fol", "skill": "test-runner", "ts": base + 1000},
        {"prompt_hash": "thin", "skill": "docs", "ts": base + 2000},  # 1 route, no follow
    ]
    invs = [{"skill": "test-runner", "ts": base + 1030}]
    stats = preview(routes, invs)
    assert stats == {"seen": 3, "would_reinforce": 1, "would_demote": 1, "thin": 1}


def test_demoted_seed_is_excluded_by_matcher(store, monkeypatch):
    # Prove the loop actually closes: a demoted seed stops being returned by the
    # matcher, while a live one is still matched.
    _seed(store, "dead", "refactor", emb=(1.0, 0.0, 0.0))
    _seed(store, "live", "test-runner", emb=(1.0, 0.0, 0.0))
    base = 1_800_000_000.0
    reconcile_outcomes(
        store,
        [{"prompt_hash": "dead", "skill": "refactor", "ts": base},
         {"prompt_hash": "dead", "skill": "refactor", "ts": base + 300},
         {"prompt_hash": "live", "skill": "test-runner", "ts": base + 600}],
        [{"skill": "test-runner", "ts": base + 630}],
    )
    from sentigent.routing import matcher
    monkeypatch.setattr(matcher, "encode", lambda _t: [1.0, 0.0, 0.0])
    results = matcher.match_seeds("some task", store)
    skills = {r.skill for r in results}
    assert "test-runner" in skills
    assert "refactor" not in skills  # demoted seed excluded
