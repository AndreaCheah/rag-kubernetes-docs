# Document Ingestion (`ingest.py`)

## What problem does it solve?

Raw Kubernetes Markdown files contain Hugo shortcodes (`{{< note >}}`), HTML comments (`<!-- overview -->`), and YAML front matter (`title: "..."`, `weight: 10`). These are rendering instructions, not documentation content. If they end up in embeddings, they dilute the semantic signal and add noise to retrieval.

Ingestion cleans each file and produces a structured record with the content separated from metadata.

## The stages

### 1. Read the raw file

```
"---\ntitle: \"Viewing Pods\"\nweight: 10\n---\n\n<!-- overview -->\n\n{{< glossary_definition ... >}}\n\nUse `kubectl get pods`..."
```

### 2. Parse front matter (`_parse_front_matter`)

Separate the YAML block between `---` delimiters from the body. We want the `title` for citations but don't want it mixed into the text.

```
front_matter = {"title": "Viewing Pods", "weight": "10"}
body = "<!-- overview -->\n\n{{< glossary_definition ... >}}\n\nUse `kubectl get pods`..."
```

Why not use a YAML library? The front matter is simple key-value pairs. Our parser is ~20 lines, zero dependencies, and handles every file in the corpus.

### 3. Clean markdown (`clean_markdown`)

Order matters:

1. **Hugo heading shortcodes -> keep the text**: `{{%heading "Pod Lifecycle"%}}` -> `Pod Lifecycle`
2. **Hugo includes -> note what was included**: `{{< include "task-prereqs.md" >}}` -> `(see included file: task-prereqs.md)`
3. **HTML comments -> remove**: `<!-- overview -->` -> (empty)
4. **Remaining Hugo shortcodes -> remove**: `{{< glossary_definition ... >}}` -> (empty)
5. **Collapse blank lines**: `\n\n\n\n` -> `\n\n`

Heading shortcodes are processed first because they contain useful text that the catch-all regex would otherwise delete.

After cleaning:

```
Use `kubectl get pods` to list all pods.

You need RBAC permissions to list pods.
```

### 4. Build the IngestedDocument

```python
IngestedDocument(
    id="tasks/viewing-pods",               # from file path -- stable, deterministic
    text="Use `kubectl get pods`...",       # cleaned content
    metadata={
        "title": "Viewing Pods",            # from front matter -- for citations
        "url": "https://kubernetes.io/...", # derived from path -- for user verification
        "source_file": "tasks/viewing-pods.md",
    },
)
```

## Design decisions

### Why use the file path as the document ID?

- **Deterministic**: the same file always gets the same ID, so re-running ingestion doesn't create duplicates in the vector store
- **Human-readable**: `tasks/viewing-pods` tells you exactly what doc it is; a hash like `a7f3b2c1...` doesn't
- **Already unique**: no two files share the same path

### Why derive the URL from the path?

The Kubernetes website serves docs at paths that mirror the repository layout. `tasks/viewing-pods.md` -> `kubernetes.io/docs/tasks/viewing-pods/`. This URL is the citation link users will click to verify the answer.

### Why JSONL output?

- Stream/append without loading everything into memory
- Inspect individual records with `head -n 1`
- Standard format for ML/NLP pipelines

## Input/Output

**Input**: ~1,570 Markdown files under `corpus/kubernetes-website/content/en/docs/`

**Output**: `data/documents.jsonl` -- 1,514 records (56 empty pages skipped), one JSON object per line:

```json
{"id": "concepts/overview/kubectl", "text": "The kubectl tool...", "metadata": {"title": "kubectl", "url": "https://kubernetes.io/docs/concepts/overview/kubectl/", "source_file": "concepts/overview/kubectl.md"}}
```
