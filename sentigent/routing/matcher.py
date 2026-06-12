"""Embedding-based routing matcher.

Given a task description, encodes it and ranks stored routing_seeds by cosine
similarity, returning the top candidates above the confidence threshold.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .embeddings import encode, cosine_sim

if TYPE_CHECKING:
    from sentigent.memory.store import MemoryStore

MATCH_THRESHOLD = 0.60
TOP_K = 5


@dataclass
class RouteMatch:
    skill: str
    agent: str
    model: str
    confidence: float
    task_type: str
    outcome: str
    source: str = "embedding"
    neighbors: list[dict[str, Any]] = field(default_factory=list)


def match_seeds(task_text: str, store: "MemoryStore") -> list[RouteMatch]:
    """Return ranked RouteMatch list for *task_text* against stored routing seeds.

    Only seeds with cosine similarity >= MATCH_THRESHOLD are returned.
    Seeds with outcome='incorrect' are excluded.
    Results are sorted by similarity descending.
    """
    if not task_text or not task_text.strip():
        return []

    query_vec = encode(task_text)
    seeds = store.get_all_routing_seeds_with_embeddings()

    scored: list[tuple[float, dict[str, Any]]] = []
    for seed in seeds:
        if seed.get("outcome") == "incorrect":
            continue
        emb = seed.get("embedding")
        if not emb:
            continue
        sim = cosine_sim(query_vec, emb)
        if sim >= MATCH_THRESHOLD:
            scored.append((sim, seed))

    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[RouteMatch] = []
    for sim, seed in scored[:TOP_K]:
        results.append(RouteMatch(
            skill=seed.get("skill", ""),
            agent=seed.get("agent", "general-purpose"),
            model=seed.get("model", "sonnet"),
            confidence=sim,
            task_type=seed.get("task_type", "unknown"),
            outcome=seed.get("outcome", "neutral"),
            neighbors=seed.get("neighbors") or [],
        ))

    return results
