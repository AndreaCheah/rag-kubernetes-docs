"""
Phase 1 - Step 3: Chunking.

Goal: split ingested documents into retrieval-sized pieces that are small
enough to rank precisely, but large enough to carry meaningful context.

Why chunk at all?
-----------------
Embedding models map text to a single vector.  A 5000-token page about
"Services, Pods, and Deployments" produces one vector that is a *blend*
of all three topics.  When a user asks "how do I list pods?", that blended
vector matches weakly.  A 400-token chunk focused on "listing pods" matches
strongly — precision goes up.

Why split on Markdown headings first?
-------------------------------------
Headings are topic boundaries chosen by the doc authors.  Splitting on `##`
or `###` gives us chunks that are *semantically* coherent, not just the
right size.  Random 500-char windows would cut mid-sentence and mix topics.

Why add heading context?
-------------------------
A chunk under "### kubectl get" inside "## Viewing Resources" is meaningless
in isolation — retrieved out of context, the reader (and the LLM) wouldn't
know what "get" refers to.  Prepending the heading breadcrumb
("Viewing Resources > kubectl get") makes each chunk self-contained.

Why overlap?
------------
Even with heading-based splits, a paragraph at the very end of chunk N
might set up context that the first paragraph of chunk N+1 depends on.
Overlapping ~100 tokens means that sentence appears in both chunks, so
at least one of them will retrieve correctly for a query about it.
"""

from __future__ import annotations
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict


class _Section(TypedDict):
    heading: Optional[str]
    level: int
    body: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_CHUNK_TOKENS = 800   # Above this, split the section into paragraphs
OVERLAP_TOKENS = 100     # Approximate token overlap between consecutive chunks

# Rough token estimate: 1 token ≈ 4 characters for English text.
# Why not use a real tokenizer?  For Phase 1, a fast approximation is fine.
# The exact boundary doesn't matter much — what matters is that chunks are
# in the right *ballpark* (a few hundred tokens).  We can swap in tiktoken
# or a HuggingFace tokenizer later without changing the architecture.
CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """One retrieval unit.

    - `id`: deterministic, format "{doc_id}#chunk{index}" so it's traceable
      back to the source document and unique across the corpus.
    - `text`: the chunk content, prefixed with heading context.
    - `metadata`: inherits everything from the parent document, plus
      `chunk_index` and `heading` for debugging and citation anchoring.
    """

    id: str
    text: str
    metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Matches Markdown headings: ## Heading text
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // CHARS_PER_TOKEN


def _split_into_sections(text: str) -> List[_Section]:
    """Split Markdown text into sections based on headings.

    Returns a list of _Section dicts with heading, level, and body.

    The first section (before any heading) gets heading=None.
    Each subsequent section starts at a heading line and runs until the next
    heading of equal or higher level (or end of text).
    """

    sections: List[_Section] = []

    headings = list(_HEADING_RE.finditer(text))

    if not headings or headings[0].start() > 0:
        # Text before the first heading (or no headings at all)
        preamble = text[:headings[0].start()] if headings else text
        preamble = preamble.strip()
        if preamble:
            sections.append({"heading": None, "level": 0, "body": preamble})

    for i, match in enumerate(headings):
        level = len(match.group(1))       # number of '#' characters
        heading_text = match.group(2).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()

        sections.append({
            "heading": heading_text,
            "level": level,
            "body": body,
        })

    return sections


def _build_heading_context(sections: List[_Section], index: int) -> str:
    """Build a heading breadcrumb for a section by looking at ancestor headings.

    For a section at level 3 ("### kubectl get"), we walk backward to find
    the nearest level-2 and level-1 headings, producing something like:
        "Working with Pods > Viewing Resources > kubectl get"

    This breadcrumb is prepended to the chunk text so it's self-contained.
    """

    current = sections[index]
    if current["heading"] is None:
        return ""

    ancestors: list[str] = []
    target_level = current["level"] - 1

    # Walk backward, collecting one ancestor per level
    for j in range(index - 1, -1, -1):
        sec = sections[j]
        if sec["heading"] is not None and sec["level"] <= target_level:
            ancestors.append(sec["heading"])
            target_level = sec["level"] - 1
            if target_level < 1:
                break

    ancestors.reverse()
    ancestors.append(current["heading"])
    return " > ".join(ancestors)


def _split_long_section(text: str, max_tokens: int) -> List[str]:
    """Split a too-long section into paragraph-based pieces.

    Paragraphs are separated by blank lines.  We greedily accumulate
    paragraphs until adding the next one would exceed max_tokens, then
    start a new piece.

    If a single paragraph exceeds max_tokens (e.g. a huge code block),
    we keep it as-is rather than splitting mid-sentence.  In Phase 2
    we can add sentence-level splitting if needed.
    """

    paragraphs = re.split(r"\n{2,}", text)
    pieces: List[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_tokens = _estimate_tokens(para)

        if current and (current_tokens + para_tokens > max_tokens):
            pieces.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens

    if current:
        pieces.append("\n\n".join(current))

    return pieces


def _add_overlap(chunks_text: List[str], overlap_tokens: int) -> List[str]:
    """Prepend the tail of the previous chunk to each subsequent chunk.

    Why not append instead of prepend?  Prepending means the *start* of
    each chunk contains bridging context from the previous one, which reads
    more naturally and matches how people scan text top-to-bottom.
    """

    if len(chunks_text) <= 1:
        return chunks_text

    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    result = [chunks_text[0]]

    for i in range(1, len(chunks_text)):
        prev = chunks_text[i - 1]
        # Take the tail of the previous chunk
        overlap_text = prev[-overlap_chars:] if len(prev) > overlap_chars else prev
        # Find the first word boundary to avoid cutting mid-word
        space_idx = overlap_text.find(" ")
        if space_idx > 0:
            overlap_text = overlap_text[space_idx + 1:]
        result.append(overlap_text + "\n\n" + chunks_text[i])

    return result


# ---------------------------------------------------------------------------
# Main chunking logic
# ---------------------------------------------------------------------------

def chunk_document(
    doc_id: str,
    text: str,
    doc_metadata: Dict[str, Any],
) -> List[Chunk]:
    """Split one ingested document into retrieval-sized chunks.

    Pipeline:
    1. Split text into sections by Markdown headings.
    2. Split oversized sections (> MAX_CHUNK_TOKENS) by paragraphs.
    3. Prepend heading breadcrumb to each chunk for context.
    4. Apply token overlap between consecutive chunks.

    Short sections are kept as-is.  A 30-token section like "Delete a Pod:
    `kubectl delete pod <name>`" is specific and embeds precisely — merging
    it with a neighbor would dilute that specificity.  If evaluation later
    shows that tiny filler chunks hurt retrieval, we can filter them at
    query time rather than destroying data at index time.
    """

    sections = _split_into_sections(text)

    # --- Phase A: split oversized sections by paragraphs ---
    raw_chunks: List[tuple[str, str]] = []  # (text, heading_context)

    for i, sec in enumerate(sections):
        heading_ctx = _build_heading_context(sections, i)

        if _estimate_tokens(sec["body"]) > MAX_CHUNK_TOKENS:
            pieces = _split_long_section(sec["body"], MAX_CHUNK_TOKENS)
            for piece in pieces:
                raw_chunks.append((piece, heading_ctx))
        else:
            raw_chunks.append((sec["body"], heading_ctx))

    # --- Phase B: prepend heading context ---
    texts: List[str] = []
    headings: List[str] = []
    for body, heading_ctx in raw_chunks:
        if heading_ctx:
            texts.append(f"[{heading_ctx}]\n\n{body}")
        else:
            texts.append(body)
        headings.append(heading_ctx)

    # --- Phase C: apply overlap ---
    texts = _add_overlap(texts, OVERLAP_TOKENS)

    # --- Build Chunk objects ---
    chunks: List[Chunk] = []
    for i, chunk_text in enumerate(texts):
        chunks.append(Chunk(
            id=f"{doc_id}#chunk{i}",
            text=chunk_text,
            metadata={
                **doc_metadata,
                "chunk_index": i,
                "heading": headings[i] if i < len(headings) else "",
            },
        ))

    return chunks


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    in_path = Path("data/documents.jsonl")
    out_path = Path("data/chunks.jsonl")

    if not in_path.exists():
        print(f"Input not found: {in_path}  (run ingest.py first)")
        return 1

    total_chunks = 0

    with (
        open(in_path, encoding="utf-8") as fin,
        open(out_path, "w", encoding="utf-8") as fout,
    ):
        for line in fin:
            doc = json.loads(line)
            chunks = chunk_document(doc["id"], doc["text"], doc["metadata"])
            for chunk in chunks:
                fout.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
            total_chunks += len(chunks)

    print(f"Produced {total_chunks} chunks from {in_path}")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
