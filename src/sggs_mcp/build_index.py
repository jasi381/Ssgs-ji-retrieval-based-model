"""
Build multilingual semantic vector index for SGGS MCP.

Reads output/embedding_chunks.jsonl, embeds each chunk with
intfloat/multilingual-e5-base (offline, no API key needed),
and persists a chromadb collection at output/chroma/.

Run once after extract_multilingual.py. Safe to rerun — clears the
old collection and rebuilds.

Usage:
    python3 scripts/build_index.py
"""

import json
import sys
import time

from .config import chroma_dir, data_dir

CHUNKS_JSONL = data_dir() / "embedding_chunks.jsonl"
CHROMA_DIR = str(chroma_dir())
COLLECTION_NAME = "sggs_multilingual"
MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 256  # safe for 8 GB RAM


def main():
    print(f"Loading chunks from {CHUNKS_JSONL} ...")
    chunks = []
    with open(CHUNKS_JSONL, encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                chunks.append(json.loads(raw))
    print(f"  {len(chunks)} chunks loaded.")

    print(f"Loading model {MODEL_NAME} (downloads once, cached) ...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"  Model ready in {time.time()-t0:.1f}s")

    print(f"Opening chromadb at {CHROMA_DIR} ...")
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Clear existing collection so rerun is idempotent
    try:
        client.delete_collection(COLLECTION_NAME)
        print("  Deleted existing collection.")
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    total = len(chunks)
    embedded = 0
    t_embed = time.time()

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]

        # e5 prefix: "passage: " for documents
        texts = ["passage: " + ch["text"] for ch in batch]
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

        ids = [ch["chunk_id"] for ch in batch]
        metadatas = [
            {
                "chunk_type": ch["chunk_type"],
                "ang": ch["ang"],
                "author": ch["author"],
                "raaga": ch["raaga"],
                "line_ids": ch["line_ids"],
                "shabad_ids": ch["shabad_ids"],
            }
            for ch in batch
        ]
        documents = [ch["text"] for ch in batch]

        collection.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            metadatas=metadatas,
            documents=documents,
        )

        embedded += len(batch)
        elapsed = time.time() - t_embed
        rate = embedded / elapsed if elapsed > 0 else 0
        eta = (total - embedded) / rate if rate > 0 else 0
        print(
            f"  {embedded}/{total} embedded | {rate:.0f}/s | ETA {eta:.0f}s    ",
            end="\r",
            flush=True,
        )

    elapsed = time.time() - t_embed
    print(f"\n  Done. {total} chunks indexed in {elapsed:.1f}s.")
    print(f"  Collection '{COLLECTION_NAME}' persisted at {CHROMA_DIR}")
    print("\nIndex built successfully.")


if __name__ == "__main__":
    if not CHUNKS_JSONL.exists():
        print(f"ERROR: {CHUNKS_JSONL} not found. Run extract_multilingual.py first.", file=sys.stderr)
        sys.exit(1)
    main()
