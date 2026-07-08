"""Phase 5: Semantic Memory — sentence embedding for episode retrieval.

Provides a lazy singleton for all-MiniLM-L6-v2 (384 dimensions).
Optional dependency: if sentence-transformers is not installed, all methods
return None and callers fall back gracefully to TF-IDF.

Model properties:
  - all-MiniLM-L6-v2: 384 dimensions, ~22MB, ~90ms first inference
  - Zero infrastructure — runs in process, no GPU required
  - Cosine similarity via numpy dot product on normalized vectors

Usage::

    from sentigent.core.embedder import get_embedder

    embedder = get_embedder()
    if embedder:
        vec = embedder.encode("fix the auth bug in middleware.py")  # list[float] len 384
        vecs = embedder.encode_batch(["task A", "task B"])           # list[list[float]]
        sim = embedder.cosine_similarity(vec, other_vec)             # float 0.0–1.0
    # If embedder is None, fall back to TF-IDF
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

_lock = threading.Lock()
_embedder_instance: "Embedder | None | bool" = False  # False = not yet tried


class Embedder:
    """Thin wrapper around SentenceTransformer for episode encoding."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIM = 384

    def __init__(self, model: object) -> None:
        self._model = model

    def encode(self, text: str) -> list[float]:
        """Encode a single text string to a 384-dim normalized float vector."""
        try:
            vec = self._model.encode(  # type: ignore[attr-defined]
                text,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return vec.tolist()
        except Exception as exc:
            logger.debug("embed encode failed: %s", exc)
            return []

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts. Returns list of 384-dim vectors."""
        if not texts:
            return []
        try:
            vecs = self._model.encode(  # type: ignore[attr-defined]
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=32,
            )
            return [v.tolist() for v in vecs]
        except Exception as exc:
            logger.debug("embed encode_batch failed: %s", exc)
            return []

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity for pre-normalized vectors (dot product).

        Both vectors must be L2-normalized (as produced by encode/encode_batch).
        """
        if not a or not b or len(a) != len(b):
            return 0.0
        try:
            return float(sum(x * y for x, y in zip(a, b)))
        except Exception:
            return 0.0


def get_embedder() -> "Embedder | None":
    """Return the singleton Embedder, or None if unavailable.

    First call loads the model (~22MB, ~1s on cold start). Subsequent calls
    return the cached instance immediately. Thread-safe.

    Returns None if sentence-transformers is not installed.
    """
    global _embedder_instance
    if _embedder_instance is not False:
        return _embedder_instance  # type: ignore[return-value]

    with _lock:
        if _embedder_instance is not False:
            return _embedder_instance  # type: ignore[return-value]
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
            # First call on a machine that hasn't cached this model yet triggers a
            # ~90MB one-time download from Hugging Face Hub. Print to stderr (never
            # stdout — this path can run inside an MCP stdio server) so the caller
            # sees *something* instead of a silent multi-second/minute stall.
            print(
                f"[sentigent] Loading semantic embedding model ({Embedder.MODEL_NAME}) "
                "— first run may download ~90MB, one-time...",
                file=sys.stderr,
                flush=True,
            )
            model = SentenceTransformer(Embedder.MODEL_NAME)
            _embedder_instance = Embedder(model)
            logger.info(
                "semantic embedder loaded: %s (%d dims)",
                Embedder.MODEL_NAME, Embedder.DIM,
            )
        except ImportError:
            logger.debug(
                "sentence-transformers not installed — semantic retrieval unavailable. "
                "Install with: pip install sentigent[embeddings]"
            )
            _embedder_instance = None
        except Exception as exc:
            print(
                f"[sentigent] Embedding model unavailable ({exc}) — falling back to TF-IDF.",
                file=sys.stderr,
                flush=True,
            )
            logger.warning("embedder init failed: %s — falling back to TF-IDF", exc)
            _embedder_instance = None

    return _embedder_instance  # type: ignore[return-value]
