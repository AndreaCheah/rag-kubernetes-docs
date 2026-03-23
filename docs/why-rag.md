# Why RAG?

## The problem

A user asks: "CLI command to get all pods".

**Without RAG**, an LLM answers from its training data — which may be outdated, hallucinated, or missing version-specific details. There is no way to verify the answer.

**With RAG**, we:

1. **Search** the actual Kubernetes docs for chunks relevant to "get all pods"
2. **Feed** those chunks to the LLM as context
3. **Ask** the LLM to answer *only from the provided context* and cite its sources

The user gets an answer grounded in real docs, with a link like `kubernetes.io/docs/reference/kubectl/cheatsheet/` they can click to verify.

## The pipeline

```
Raw .md files on disk
        |
        v
   ingest.py    1 file -> 1 document (cleaned text + metadata)
        |
        |  data/documents.jsonl
        v
   chunk.py     1 document -> N chunks (retrieval-sized pieces)
        |
        |  data/chunks.jsonl
        v
   index.py     embed chunks + store in vector DB
        |
        |  data/chromadb/
        v
   query.py     user question -> retrieve chunks -> LLM generates cited answer
```
