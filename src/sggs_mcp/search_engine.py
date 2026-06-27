"""
Multilingual semantic search engine for SGGS MCP.

Loads intfloat/multilingual-e5-base and queries a portable numpy index:
  output/embeddings.npy       — float16 [N, 768], cross-platform portable
  output/embedding_meta.jsonl — chunk metadata (one JSON row per vector)

No ChromaDB / HNSW — pure numpy cosine similarity so the same files work
on macOS, Linux, and Windows without rebuild.

Build the index:
    sggs-mcp build-index

Used by server.py — import `engine` and call engine.query().
Lazy-initialises on first use so MCP startup stays fast.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .config import data_dir

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"

_PERMANENT_ERROR_TYPES = (ImportError, ModuleNotFoundError)


def _embeddings_path() -> Path:
    return data_dir() / "embeddings.npy"


def _meta_path() -> Path:
    return data_dir() / "embedding_meta.jsonl"


class SemanticEngine:
    """Lazy-loading multilingual semantic search over the SGGS corpus."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._embeddings: np.ndarray | None = None  # float32 [N, 768]
        self._meta: list[dict] = []
        self._ready = False
        self._error: str | None = None
        self._permanent: bool = False
        self._lock = threading.Lock()

    def _init(self) -> None:
        if self._ready or self._permanent:
            return
        with self._lock:
            if self._ready or self._permanent:
                return
            try:
                from sentence_transformers import SentenceTransformer

                emb_path = _embeddings_path()
                meta_path = _meta_path()

                if not emb_path.exists() or not meta_path.exists():
                    self._error = (
                        "Semantic index not built yet. "
                        "Run: sggs-mcp build-index"
                    )
                    self._permanent = True
                    return

                # float16 on disk → float32 for math
                self._embeddings = np.load(str(emb_path)).astype(np.float32)

                if self._embeddings.shape[0] == 0:
                    self._error = (
                        "Semantic index is empty (0 vectors). "
                        "Run: sggs-mcp build-index"
                    )
                    return  # transient — allow retry after rebuild

                with open(meta_path, encoding="utf-8") as f:
                    self._meta = [json.loads(line) for line in f if line.strip()]

                if len(self._meta) != self._embeddings.shape[0]:
                    self._error = (
                        f"Index mismatch: {self._embeddings.shape[0]} vectors "
                        f"but {len(self._meta)} metadata rows. Run build-index."
                    )
                    return  # transient

                self._model = SentenceTransformer(MODEL_NAME)
                self._ready = True
                self._error = None

            except _PERMANENT_ERROR_TYPES as e:
                self._error = (
                    f"Missing dependency: {e}. "
                    "Run: pip3 install sentence-transformers"
                )
                self._permanent = True
            except Exception as e:
                self._error = f"Semantic engine init failed: {e}"

    def is_ready(self) -> bool:
        self._init()
        return self._ready

    def count(self) -> int:
        if self._ready and self._embeddings is not None:
            return int(self._embeddings.shape[0])
        return 0

    def status(self) -> str:
        self._init()
        if self._ready:
            return f"ready ({self._embeddings.shape[0]} vectors, numpy)"
        return f"unavailable — {self._error}"

    def query(self, query: str, k: int = 8) -> list[dict]:
        """
        Embed the query and return the top-k matching chunks.

        Returns [] on any failure — callers fall back to lexical search.
        """
        self._init()
        if not self._ready:
            return []

        try:
            vec = self._model.encode(
                "query: " + query,
                normalize_embeddings=True,
            ).astype(np.float32)
        except Exception:
            return []

        # Cosine similarity = dot product (vectors are L2-normalised)
        scores = self._embeddings @ vec  # shape [N]
        n = min(k, len(scores))
        top_idx = np.argpartition(scores, -n)[-n:]
        top_idx = top_idx[np.argsort(-scores[top_idx])]

        hits = []
        for idx in top_idx:
            meta = self._meta[int(idx)]
            hits.append({
                "chunk_id":   meta.get("chunk_id", str(idx)),
                "chunk_type": meta.get("chunk_type", ""),
                "ang":        meta.get("ang", ""),
                "author":     meta.get("author", ""),
                "raaga":      meta.get("raaga", ""),
                "line_ids":   meta.get("line_ids", "[]"),
                "shabad_ids": meta.get("shabad_ids", "[]"),
                "text":       meta.get("text", ""),
                "distance":   round(float(1.0 - scores[idx]), 4),
            })
        return hits


# Module-level singleton — imported by server.py
engine = SemanticEngine()
