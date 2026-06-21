"""
Multilingual semantic search engine for SGGS MCP.

Loads intfloat/multilingual-e5-base (offline, cached by sentence-transformers)
and queries the chromadb collection built by scripts/build_index.py.

Used by mcp_server.py — import engine and call engine.query().
The engine lazy-initialises on first use so MCP startup stays fast.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from .config import chroma_dir

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

CHROMA_DIR = str(chroma_dir())
COLLECTION_NAME = "sggs_multilingual"
MODEL_NAME = "intfloat/multilingual-e5-base"

# Errors that mean the engine can never work (missing deps/index) — no retry.
_PERMANENT_ERROR_TYPES = (ImportError, ModuleNotFoundError)


class SemanticEngine:
    """Lazy-loading multilingual semantic search over the SGGS corpus."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._collection = None
        self._ready = False
        self._error: str | None = None
        self._permanent: bool = False   # if True, do not retry
        self._lock = threading.Lock()   # Fix 6: thread-safe init

    def _init(self) -> None:
        # Fast path — no lock needed once ready or permanently failed.
        if self._ready or self._permanent:
            return
        with self._lock:
            # Double-checked locking — re-check inside lock.
            if self._ready or self._permanent:
                return
            try:
                from sentence_transformers import SentenceTransformer
                import chromadb

                chroma_path = Path(CHROMA_DIR)
                if not chroma_path.exists():
                    # Missing index is permanent until user runs build_index.py.
                    self._error = (
                        "Semantic index not built yet. "
                        "Run: sggs-mcp build-index"
                    )
                    self._permanent = True
                    return

                self._model = SentenceTransformer(MODEL_NAME)
                client = chromadb.PersistentClient(path=CHROMA_DIR)
                self._collection = client.get_collection(COLLECTION_NAME)
                vector_count = self._collection.count()
                if vector_count == 0:
                    self._error = (
                        "Semantic index is empty (0 vectors). "
                        "Run: sggs-mcp build-index and redeploy."
                    )
                    # Transient — allow retry after a good redeploy.
                    return
                self._ready = True
                self._error = None
            except _PERMANENT_ERROR_TYPES as e:
                # Missing package — permanent.
                self._error = (
                    f"Missing dependency: {e}. "
                    "Run: pip3 install sentence-transformers chromadb"
                )
                self._permanent = True
            except Exception as e:
                # Transient (disk busy, chroma timeout…) — allow retry.
                self._error = f"Semantic engine init failed: {e}"
                # _permanent stays False → next call retries.

    def is_ready(self) -> bool:
        self._init()
        return self._ready

    def count(self) -> int:
        """Return number of indexed vectors, or 0 if not ready."""
        if self._ready and self._collection is not None:
            return self._collection.count()
        return 0

    def status(self) -> str:
        self._init()
        if self._ready:
            return f"ready (collection: {COLLECTION_NAME})"
        return f"unavailable — {self._error}"

    def query(self, query: str, k: int = 8) -> list[dict]:
        """
        Embed the query and return the top-k matching chunks.

        Returns a list of dicts:
          {chunk_id, chunk_type, ang, author, raaga, line_ids, shabad_ids, text, distance}

        Returns [] on any failure (init not ready, inference error, chroma error).
        Errors are non-fatal — callers fall back to lexical search.
        """
        self._init()
        if not self._ready:
            return []

        try:
            # Fix 5: wrap encode + chroma query in try/except.
            vec = self._model.encode(
                "query: " + query,
                normalize_embeddings=True,
            ).tolist()
        except Exception:
            return []

        try:
            results = self._collection.query(
                query_embeddings=[vec],
                n_results=min(k, self._collection.count()),
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            return []

        hits = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            hits.append(
                {
                    "chunk_id": results["ids"][0][i],
                    "chunk_type": meta.get("chunk_type", ""),
                    "ang": meta.get("ang", ""),
                    "author": meta.get("author", ""),
                    "raaga": meta.get("raaga", ""),
                    "line_ids": meta.get("line_ids", "[]"),
                    "shabad_ids": meta.get("shabad_ids", "[]"),
                    "text": results["documents"][0][i],
                    "distance": round(results["distances"][0][i], 4),
                }
            )
        return hits


# Module-level singleton — imported by mcp_server
engine = SemanticEngine()
