"""
Phase 1 - Step 2: Document ingestion.

Goal: convert raw Kubernetes Markdown pages into a normalized JSONL dataset.
"""

from __future__ import annotations
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class IngestedDocument:
    """
    Unit of ingestion: one doc page.

    - `id` is stable and deterministic (so citations don't change across runs)
    - `text` is the cleaned content we'll chunk later
    - `metadata` stores anything needed for citations/debugging (title, url, source file)
    """

    id: str
    text: str
    metadata: Dict[str, Any]


K8S_DOCS_BASE_URL = "https://kubernetes.io/docs/"
_FRONT_MATTER_DELIM_RE = re.compile(r"^---\s*$", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--([\s\S]*?)-->")
_HUGO_HEADING_RE = re.compile(r"\{\{%+\s*heading\s+\"([^\"]+)\"\s*%+\}\}")
_HUGO_INCLUDE_RE = re.compile(r"\{\{<\s*include\s+\"([^\"]+)\"\s*>}}")
_HUGO_SHORTCODE_RE = re.compile(r"\{\{[<%].*?[>%]}}")


def clean_markdown(body: str) -> str:
    """Remove non-content artifacts from a Markdown body.

    1. Hugo heading shortcodes → keep the text
      "{{%heading \"Pod Lifecycle\"%}}"  →  "Pod Lifecycle"

    2. Hugo includes → note what was included (we can't resolve it)
      "{{< include \"task-prereqs.md\" >}}"  →  "(see included file: task-prereqs.md)"

    3. HTML comments → remove entirely
      "<!-- overview -->"  →  ""

    4. Remaining Hugo shortcodes → remove entirely
      "{{< glossary_definition ... >}}"  →  ""
      "{{< note >}}"  →  ""

    5. Collapse excessive blank lines
      "\n\n\n\n"  →  "\n\n"
    """

    text = _HUGO_HEADING_RE.sub(r"\1", body)
    text = _HUGO_INCLUDE_RE.sub(r"(see included file: \1)", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HUGO_SHORTCODE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def iter_markdown_paths(docs_root: Path) -> Iterable[Path]:
    """
    Yield all Markdown files under the docs root.

    This will walk:
      corpus/kubernetes-website/content/en/docs/**/*.md
    """

    docs_root = docs_root.resolve()
    if not docs_root.exists():
        raise FileNotFoundError(f"Docs root does not exist: {docs_root}")

    yield from docs_root.rglob("*.md")


def _parse_front_matter(md: str) -> tuple[Dict[str, Any], str]:
    """Parse optional Hugo front matter and return (meta, body).

    Args:
        md: Raw Markdown file contents.

    Returns:
        A tuple (meta, body) where:
        - meta is a dict of simple top-level `key: value` pairs parsed from a
          `---` delimited front matter block at the start of the file.
        - body is the remaining Markdown content, with leading blank lines removed.

    Notes:
        - If the file doesn't start with `---` or the delimiter pair is malformed,
          this returns ({}, md). This avoids misinterpreting later `---` horizontal
          rules as front matter.
        - Nested YAML structures are ignored for Phase 1 ingestion.
        - Values containing `:` are handled by splitting on the first colon only.
        - Quoted values like `title: "..."` have surrounding quotes removed for display/citations.
    """

    if not md.startswith("---"):
        return {}, md

    delimiter_lines = list(_FRONT_MATTER_DELIM_RE.finditer(md))

    if len(delimiter_lines) < 2 or delimiter_lines[0].start() != 0:
        return {}, md

    end_of_first_delimiter = delimiter_lines[0].end()
    start_of_second_delimiter = delimiter_lines[1].start()
    front_matter = md[end_of_first_delimiter:start_of_second_delimiter]

    end_of_second_delimiter = delimiter_lines[1].end()
    body = md[end_of_second_delimiter :]

    front_matter_dict: Dict[str, Any] = {}
    for raw_line in front_matter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        front_matter_dict[key] = value

    return front_matter_dict, body.lstrip("\n")




def _path_to_doc_id(path: Path, docs_root: Path) -> str:
    """Derive a stable document ID from its file path.

    Uses the path relative to the docs root, without extension, using forward
    slashes.  Example:
        docs_root / concepts / overview / kubectl.md  →  "concepts/overview/kubectl"

    Why the relative path and not a hash?  It's human-readable, deterministic,
    and already unique within the corpus.  If the same file is ingested again,
    it produces the same ID — so the vector store can upsert without creating
    duplicates.
    """

    relative = path.relative_to(docs_root.resolve())
    return relative.with_suffix("").as_posix()


def _path_to_url(doc_id: str) -> str:
    """Convert a doc ID to its canonical kubernetes.io URL.

    The Kubernetes website serves docs at paths that mirror the repository
    layout, with _index files mapping to the directory URL:
        concepts/overview/kubectl  →  https://kubernetes.io/docs/concepts/overview/kubectl/
        concepts/overview/_index   →  https://kubernetes.io/docs/concepts/overview/
    """

    # _index files represent the directory landing page
    url_path = doc_id.replace("/_index", "").rstrip("/")
    return f"{K8S_DOCS_BASE_URL}{url_path}/"


def ingest_document(path: Path, docs_root: Path) -> IngestedDocument | None:
    """Read, parse, and clean a single Markdown file into an IngestedDocument.

    Returns None for files that produce no usable text after cleaning (e.g.
    pages that are entirely Hugo shortcodes with no prose).
    """

    raw = path.read_text(encoding="utf-8")
    front_matter, body = _parse_front_matter(raw)
    text = clean_markdown(body)

    if not text:
        return None

    doc_id = _path_to_doc_id(path, docs_root)
    url = _path_to_url(doc_id)
    title = front_matter.get("title", doc_id)

    return IngestedDocument(
        id=doc_id,
        text=text,
        metadata={
            "title": title,
            "url": url,
            "source_file": str(path.relative_to(docs_root.resolve())),
        },
    )


def main() -> int:
    docs_root = Path("corpus/kubernetes-website/content/en/docs/")
    out_path = Path("data/documents.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    with open(out_path, "w", encoding="utf-8") as fh:
        for md_path in iter_markdown_paths(docs_root):
            doc = ingest_document(md_path, docs_root)
            if doc is None:
                skipped += 1
                continue
            fh.write(json.dumps(asdict(doc), ensure_ascii=False) + "\n")
            written += 1

    print(f"Ingested {written} documents, skipped {skipped} empty pages.")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

