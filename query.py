"""
Phase 1 - Step 5: Retrieval + answer generation with citations.

Goal: given a user question, retrieve relevant chunks from the vector store
and generate an answer grounded in those chunks with source citations.
"""

from __future__ import annotations
import os
from typing import List

import chromadb
from chromadb.api.types import Embedding
from dotenv import load_dotenv
import numpy as np
from openai import OpenAI


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_DIR = "data/chromadb"
COLLECTION_NAME = "k8s_docs"
EMBEDDING_MODEL = "text-embedding-3-small"
GENERATION_MODEL = "gpt-4o-mini"
TOP_K = 5  # number of chunks to retrieve


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve(
    query: str,
    openai_client: OpenAI,
    collection: chromadb.Collection,
    top_k: int = TOP_K,
) -> chromadb.QueryResult:
    """Embed the user query and find the top-k most similar chunks.

    Uses the same embedding model as indexing — this is critical.  Vectors
    from different models live in incompatible spaces and cannot be compared.
    """

    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[query],
    )
    query_embedding: Embedding = np.array(
        response.data[0].embedding, dtype=np.float32
    )

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    return results


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Kubernetes documentation assistant. Answer the
user's question using ONLY the provided context chunks. Follow these rules:

1. Base your answer solely on the context provided. Do not use prior knowledge.
2. Cite your sources using [Source Title](URL) format after each claim.
3. If the context does not contain enough information to answer, say so explicitly.
4. Be concise and direct. Prefer code examples when the question is about commands.
"""


def _build_context(results: chromadb.QueryResult) -> str:
    """Format retrieved chunks into a context block for the LLM prompt.

    Each chunk is labeled with its source title and URL so the LLM can
    reference them in citations.
    """

    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []

    context_parts: List[str] = []
    for i, (doc, meta) in enumerate(zip(documents, metadatas)):
        title = str(meta.get("title", "Unknown")) if meta else "Unknown"
        url = str(meta.get("url", "")) if meta else ""
        context_parts.append(
            f"--- Chunk {i + 1} ---\n"
            f"Source: [{title}]({url})\n\n"
            f"{doc}"
        )

    return "\n\n".join(context_parts)


def generate_answer(
    query: str,
    results: chromadb.QueryResult,
    openai_client: OpenAI,
) -> str:
    """Send retrieved chunks + user question to the LLM for a cited answer."""

    context = _build_context(results)

    response = openai_client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context:\n\n{context}\n\n---\n\nQuestion: {query}",
            },
        ],
        temperature=0.0,
    )

    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    load_dotenv()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set. Add it to your .env file or export it.")
        return 1

    openai_client = OpenAI()
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    if collection.count() == 0:
        print("No vectors in the collection. Run index.py first.")
        return 1

    print("Kubernetes docs RAG — type your question (or 'quit' to exit)\n")

    while True:
        query = input("Q: ").strip()
        if not query or query.lower() in ("quit", "exit", "q"):
            break

        results = retrieve(query, openai_client, collection)
        answer = generate_answer(query, results, openai_client)

        print(f"\nA: {answer}\n")

        # Show sources
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        seen_urls: set[str] = set()
        print("Sources:")
        for meta in metadatas:
            if not meta:
                continue
            url = str(meta.get("url", ""))
            title = str(meta.get("title", ""))
            if url and url not in seen_urls:
                seen_urls.add(url)
                print(f"  - [{title}]({url})")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
