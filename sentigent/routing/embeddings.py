"""Embedding engine for routing — wraps sentence-transformers with a module-level cache.

Uses all-MiniLM-L6-v2 (80 MB, 384-dim). Lazy-loaded on first call so import is instant.
Vectors are JSON-serialisable lists of floats for SQLite storage.
"""
from __future__ import annotations
import math
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer as _ST

EMBEDDING_DIM = 384
_MODEL_NAME = "all-MiniLM-L6-v2"
_model: "_ST | None" = None


def _get_model() -> "_ST":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


@lru_cache(maxsize=512)
def encode(text: str) -> tuple[float, ...]:
    """Return a normalised embedding vector for *text* as a tuple (hashable, cacheable)."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return tuple(float(v) for v in vec)


def encode_list(text: str) -> list[float]:
    """Convenience wrapper — returns a plain list for JSON serialisation."""
    return list(encode(text))


def cosine_sim(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    """Cosine similarity between two pre-normalised vectors.

    Vectors from encode() are already L2-normalised, so this is just a dot product.
    Falls back to full formula for safety.
    """
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
