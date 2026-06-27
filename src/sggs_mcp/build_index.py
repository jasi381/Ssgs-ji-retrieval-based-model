"""
Build multilingual semantic vector index for SGGS MCP.

Reads output/embedding_chunks.jsonl, embeds each chunk with
intfloat/multilingual-e5-base, and saves:
  output/embeddings.npy       — float16 array [N, 768], cross-platform portable
  output/embedding_meta.jsonl — one JSON row per chunk with chunk metadata

Cross-platform: .npy files are endian-aware and work on macOS/Linux/Windows
without rebuild — no ChromaDB HNSW binaries involved.

Usage:
    sggs-mcp build-index
"""

import json
import sys
import time

import numpy as np

from .config import data_dir

CHUNKS_JSONL = data_dir() / "embedding_chunks.jsonl"
EMBEDDINGS_NPY = data_dir() / "embeddings.npy"
META_JSONL = data_dir() / "embedding_meta.jsonl"
MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 256


def main() -> None:
    print(f"Loading chunks from {CHUNKS_JSONL} ...")
    chunks: list[dict] = []
    with open(CHUNKS_JSONL, encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                chunks.append(json.loads(raw))
    total = len(chunks)
    print(f"  {total} chunks loaded.")

    print(f"Loading model {MODEL_NAME} (downloads once, cached) ...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"  Model ready in {time.time() - t0:.1f}s")

    print("Embedding chunks ...")
    all_embeddings: list[np.ndarray] = []
    t_embed = time.time()

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = ["passage: " + ch["text"] for ch in batch]
        embs = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        all_embeddings.append(embs.astype(np.float16))

        embedded = i + len(batch)
        elapsed = time.time() - t_embed
        rate = embedded / elapsed if elapsed > 0 else 0
        eta = (total - embedded) / rate if rate > 0 else 0
        print(f"  {embedded}/{total} | {rate:.0f}/s | ETA {eta:.0f}s    ", end="\r", flush=True)

    print()
    arr = np.concatenate(all_embeddings, axis=0)  # [N, 768] float16
    np.save(str(EMBEDDINGS_NPY), arr)
    size_mb = EMBEDDINGS_NPY.stat().st_size / 1024 / 1024
    print(f"  Saved embeddings: {arr.shape}, float16, {size_mb:.0f} MB → {EMBEDDINGS_NPY}")

    print("Saving metadata ...")
    with open(META_JSONL, "w", encoding="utf-8") as f:
        for ch in chunks:
            row = {
                "chunk_id":   ch.get("chunk_id", ""),
                "chunk_type": ch.get("chunk_type", ""),
                "ang":        ch.get("ang", ""),
                "author":     ch.get("author", ""),
                "raaga":      ch.get("raaga", ""),
                "line_ids":   ch.get("line_ids", "[]"),
                "shabad_ids": ch.get("shabad_ids", "[]"),
                "text":       ch.get("text", ""),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Saved metadata: {total} rows → {META_JSONL}")

    elapsed_total = time.time() - t_embed
    print(f"\nIndex built: {total} chunks in {elapsed_total:.1f}s")


if __name__ == "__main__":
    if not CHUNKS_JSONL.exists():
        print(f"ERROR: {CHUNKS_JSONL} not found. Run extract_multilingual.py first.", file=sys.stderr)
        sys.exit(1)
    main()
