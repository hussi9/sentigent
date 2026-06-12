"""Tests for the embedding engine."""
from __future__ import annotations
import pytest
from sentigent.routing.embeddings import encode, cosine_sim, EMBEDDING_DIM


def test_encode_returns_float_array():
    vec = encode("fix the auth bug")
    assert len(vec) == EMBEDDING_DIM
    assert isinstance(vec[0], float)


def test_encode_same_text_is_deterministic():
    a = encode("deploy to production")
    b = encode("deploy to production")
    assert a == b


def test_cosine_sim_identical_is_one():
    vec = encode("add a login button")
    sim = cosine_sim(vec, vec)
    assert abs(sim - 1.0) < 1e-5


def test_cosine_sim_different_texts_is_less_than_one():
    a = encode("fix the null pointer bug")
    b = encode("deploy to staging")
    assert cosine_sim(a, b) < 0.99


def test_cosine_sim_semantically_similar_is_higher():
    bug = encode("fix the crashing test")
    also_bug = encode("debug the failing test suite")
    unrelated = encode("deploy the new release to production")
    assert cosine_sim(bug, also_bug) > cosine_sim(bug, unrelated)
