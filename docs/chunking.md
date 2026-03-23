# Chunking (`chunk.py`)

## What problem does it solve?

Embedding models convert text into a single vector. A 5,000-token page about "Services, Pods, and Deployments" produces one vector that blends all three topics. When a user asks "how do I list pods?", that blended vector matches weakly. A 400-token chunk focused on listing pods matches strongly. Smaller, focused chunks retrieve more precisely.

But too small is also bad in a different way -- not in how the vector is computed, but in how *distinguishable* it is. A 10-token chunk like "See the next section" is vague, so its vector lands in a crowded region of the embedding space near hundreds of other generic filler sentences. A 30-token chunk like "`kubectl delete pod <name>`" is short but highly specific -- its vector is sharply distinct.

The size of a chunk doesn't determine embedding quality. The *specificity of content* does.

## The pipeline (4 stages)

### Stage 1: Split by headings (`_split_into_sections`)

Markdown headings (`##`, `###`) are topic boundaries chosen by the doc authors. Splitting on them gives semantically coherent chunks, unlike fixed-character windows that would cut mid-sentence.

```
Input (one document text):
    "Pods are the smallest units.\n\n## Viewing Pods\n\nUse kubectl...\n\n### List All Pods\n\n..."

Output:
    Section 0: heading=None,            level=0, body="Pods are the smallest units."
    Section 1: heading="Viewing Pods",  level=2, body="Use kubectl..."
    Section 2: heading="List All Pods", level=3, body="To list all pods:..."
```

Text before the first heading becomes the "preamble" section (heading=None, level=0).

### Stage 2: Split oversized sections (`_split_long_section`)

If a section exceeds 800 tokens, split it by paragraphs (blank lines). Paragraphs are a coarser boundary than sentences, keeping related content together (e.g., a code block + its explanation).

The algorithm greedily accumulates paragraphs until adding the next one would exceed the limit, then starts a new piece.

```
Input: one section, 2000 tokens, 8 paragraphs
Output: 3 pieces of ~650 tokens each
```

If a single paragraph exceeds the limit (e.g., a huge code block), it's kept as-is rather than split mid-content.

### Stage 3: Prepend heading context (`_build_heading_context`)

A chunk retrieved in isolation needs context about where it came from. The heading breadcrumb solves this.

For a level-3 section, we walk backward through sections to find ancestor headings:

```
Without context:                    With context:
                                    [Viewing Pods > List All Pods]
To list all pods:
`kubectl get pods`                  To list all pods:
                                    `kubectl get pods`
```

This improves both retrieval (the embedding encodes "viewing", "pods" from the breadcrumb) and generation (the LLM knows the section context when composing an answer).

### Stage 4: Apply overlap (`_add_overlap`)

~100 tokens from the tail of the previous chunk are prepended to the start of the next chunk. This ensures that content at chunk boundaries appears in at least one chunk fully.

```
Chunk 0: [... content A ...]
Chunk 1: [tail of A ... content B ...]     <- 100 tokens from chunk 0 prepended
Chunk 2: [tail of B ... content C ...]     <- 100 tokens from chunk 1 prepended
```

Only prepend (tail of previous), not append (head of next). This makes each chunk read naturally -- bridging context first, then the section's own content.

The overlap text is snapped to a word boundary to avoid cutting mid-word.

## Design decisions

### Why no minimum chunk size?

An earlier version merged sections under 200 tokens with their neighbor. This was removed because short sections can be highly specific. A 30-token section like "Delete a Pod: `kubectl delete pod <name>`" embeds precisely -- merging it with an unrelated neighbor would dilute that specificity.

If evaluation later shows tiny filler chunks hurt retrieval, we can filter them at query time rather than destroying data at index time.

### Why split on headings instead of fixed-size windows?

Fixed-size windows cut at arbitrary positions. A 500-character window might split between `kubectl get pods` and `--all-namespaces`, producing two chunks that are each incomplete. Heading-based splits respect the topic boundaries the doc authors chose.

### Why paragraphs as the secondary split boundary?

Paragraphs keep more context together than sentences. A code block + its explanation typically live in one paragraph. Sentence splitting would risk separating a command from its description.

## Input/Output

**Input**: `data/documents.jsonl` (1,514 documents)

**Output**: `data/chunks.jsonl` (12,279 chunks), one JSON object per line:

```json
{"id": "concepts/overview/kubectl#chunk2", "text": "[Role of kubectl]\n\nThe kubectl tool...", "metadata": {"title": "kubectl", "url": "https://kubernetes.io/docs/concepts/overview/kubectl/", "chunk_index": 2, "heading": "Role of kubectl"}}
```

Each chunk inherits the parent document's metadata (title, url) and adds chunk-specific fields (chunk_index, heading).
