"""
Multilingual semantic search engine for SGGS MCP.

Loads intfloat/multilingual-e5-base (offline, cached by sentence-transformers)
and queries the chromadb collection built by scripts/build_index.py.

Used by mcp_server.py — import SemanticEngine and call semantic_query().
The engine lazy-initialises on first use so MCP startup stays fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    import chromadb as _chromadb

REPO_ROOT = Path(__file__).parent.parent
CHROMA_DIR = str(REPO_ROOT / "output" / "chroma")
COLLECTION_NAME = "sggs_multilingual"
MODEL_NAME = "intfloat/multilingual-e5-base"


class SemanticEngine:
    """Lazy-loading multilingual semantic search over the SGGS corpus."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._collection = None
        self._ready = False
        self._error: str | None = None

    def _init(self) -> None:
        if self._ready or self._error:
            return
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb

            chroma_path = Path(CHROMA_DIR)
            if not chroma_path.exists():
                self._error = (
                    "Semantic index not built yet. "
                    "Run: python3 scripts/build_index.py"
                )
                return

            self._model = SentenceTransformer(MODEL_NAME)
            client = chromadb.PersistentClient(path=CHROMA_DIR)
            self._collection = client.get_collection(COLLECTION_NAME)
            self._ready = True
        except ImportError as e:
            self._error = f"Missing dependency: {e}. Run: pip3 install sentence-transformers chromadb"
        except Exception as e:
            self._error = f"Semantic engine init failed: {e}"

    def is_ready(self) -> bool:
        self._init()
        return self._ready

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

        Returns [] if the semantic engine is not ready.
        """
        self._init()
        if not self._ready:
            return []

        # e5 prefix: "query: " for queries
        vec = self._model.encode(
            "query: " + query,
            normalize_embeddings=True,
        ).tolist()

        results = self._collection.query(
            query_embeddings=[vec],
            n_results=min(k, self._collection.count()),
            include=["metadatas", "documents", "distances"],
        )

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
