"""
Phase 1 - Step 4: Embeddings + vector store.

Goal: embed every chunk into a vector and store it in ChromaDB so we can
retrieve the most relevant chunks for a user query.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import chromadb
from chromadb.api.types import Embedding
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_DIR = "data/chromadb"
COLLECTION_NAME = "k8s_docs"
EMBEDDING_MODEL = "text-embedding-3-small"
# OpenAI's embedding API accepts up to 2048 texts per request, but smaller
# batches are more resilient to transient failures and easier to retry.
BATCH_SIZE = 100
# text-embedding-3-small accepts up to 8191 tokens per text.
# We use 2 chars/token (not 4) as a conservative estimate for truncation,
# because structured content like YAML/JSON has many short tokens where
# each symbol is its own token.
MAX_EMBEDDING_CHARS = 8191 * 2


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed_batch(client: OpenAI, texts: List[str]) -> List[Embedding]:
    """Embed a batch of texts using OpenAI's embedding API.

    Returns one vector (as a numpy float32 array) per input text, in the
    same order.  ChromaDB expects numpy arrays, not plain Python lists.
    """

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    # Sort by index defensively — the API returns them in order today,
    # but we don't want silent corruption if that ever changes.
    sorted_embeddings = sorted(response.data, key=lambda e: e.index)
    return [np.array(e.embedding, dtype=np.float32) for e in sorted_embeddings]


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_chunks(chunks_path: Path) -> None:
    """Read chunks from JSONL, embed them, and upsert into ChromaDB."""

    openai_client = OpenAI()  # reads OPENAI_API_KEY from environment

    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)

    # get_or_create: first run creates the collection, subsequent runs
    # reuse it.  upsert (below) handles deduplication by ID.
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    chunks: List[Dict[str, Any]] = []
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))

    print(f"Loaded {len(chunks)} chunks from {chunks_path}")

    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[batch_start : batch_start + BATCH_SIZE]

        ids = [c["id"] for c in batch]
        texts = [c["text"][:MAX_EMBEDDING_CHARS] for c in batch]
        metadatas = [c["metadata"] for c in batch]

        embeddings = _embed_batch(openai_client, texts)

        # Upsert: if the ID already exists, overwrite. This makes
        # re-indexing idempotent — no duplicates on repeated runs.
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        indexed_so_far = min(batch_start + BATCH_SIZE, len(chunks))
        print(f"  Indexed {indexed_so_far}/{len(chunks)} chunks")

    print(f"Done. Collection '{COLLECTION_NAME}' has {collection.count()} vectors.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    load_dotenv()  # load .env into os.environ before checking keys
    chunks_path = Path("data/chunks.jsonl")

    if not chunks_path.exists():
        print(f"Input not found: {chunks_path}  (run chunk.py first)")
        return 1

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set. Add it to your .env file or export it.")
        return 1

    index_chunks(chunks_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
