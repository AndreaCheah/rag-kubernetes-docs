# Production-Grade RAG — Technical Documentation

A retrieval-augmented generation (RAG) system for querying Kubernetes' technical documentation with citations.

## Pipeline
ingest → chunk → index → retrieve → generate → evaluate

## Phase 1: Fundamentals
Goal: given docs + question → answer with citations.

| Step | Status | Description |
|------|--------|-------------|
| 1 | Completed | Choose corpus + obtain Kubernetes docs |
| 2 | Completed | Document ingestion (load + clean Markdown) |
| 3 | Completed | Chunking (heading-based split, ~100 token overlap) |
| 4 | Pending | Embeddings + vector store |
| 5 | Pending | Retrieval + answer generation with citations |

### Phase 1 commands

```bash
python ingest.py   # Step 2: raw Markdown → data/documents.jsonl
python chunk.py    # Step 3: documents.jsonl → data/chunks.jsonl
```

## Phase 2: Production-quality retrieval + guardrails
Goal: improve retrieval precision.

| Step | Status | Description |
|------|--------|-------------|
| 1 | Pending | Add BM25 keyword index over chunks |
| 2 | Pending | Hybrid retrieval (BM25 + vector) with score fusion |
| 3 | Pending | Cross-encoder re-ranking of retrieved candidates |
| 4 | Pending | Citation enforcement + “decline to answer” when unsupported |
| 5 | Pending | Prompt versioning in config files |
| 6 | Pending | Observability (logs/traces for retrieval, context, citations) |

## Phase 3: Evaluation + CI quality gates
Goal: measure quality and prevent regressions.

| Step | Status | Description |
|------|--------|-------------|
| 1 | Pending | Curate golden dataset (50–200 Q/A pairs) |
| 2 | Pending | Offline evaluation runner that saves artifacts |
| 3 | Pending | RAG quality metrics (faithfulness, answer relevance, context quality) |
| 4 | Pending | Thresholds + regression checks (fail below baseline) |
| 5 | Pending | CI integration (run eval on PRs, publish report) |

## Corpus

- **Source**: [Kubernetes documentation](https://kubernetes.io/docs/) (English)
- **Details**: See [docs/corpus.md](./docs/corpus.md)

## Project Structure

```
rag/
├── corpus/kubernetes-website/    # Step 1: raw docs
├── data/
│   ├── documents.jsonl           # output of ingest
│   ├── chunks.jsonl              # output of chunking
│   └── chromadb/                 # vector store (output of index)
├── docs/                         # engineering rationale and decisions
│   ├── why-rag.md
│   ├── corpus.md
│   ├── ingestion.md
│   ├── chunking.md
│   └── embeddings.md
├── ingest.py                     # Step 2: markdown → documents.jsonl
├── chunk.py                      # Step 3: documents.jsonl → chunks.jsonl
├── index.py                      # Step 4: chunks.jsonl → vector store
├── query.py                      # Step 5: question → cited answer
└── README.md
```
