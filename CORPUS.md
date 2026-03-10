# Corpus Definition — Phase 1 Step 1

## Source of Truth

**Corpus**: Kubernetes official documentation (English)

| Field | Value |
|-------|-------|
| **Source** | [kubernetes/website](https://github.com/kubernetes/website) (GitHub) |
| **Content path** | `content/en/docs/` |
| **Format** | Markdown (CommonMark) with Hugo front matter |
| **License** | Apache 2.0 (per Kubernetes project) |

## Scope

- **Language**: English only (`content/en/docs/`)
- **Content**: Core documentation (concepts, tutorials, tasks, reference, setup)
- **Excluded**: Non-English locales, blog posts, release notes (unless you choose to include them later)

## Purpose

A bounded, well-structured corpus ensures:

1. **Retrieval quality** — Consistent structure and format make chunking and indexing predictable
2. **Meaningful citations** — Each chunk maps to a real doc page (e.g. `kubernetes.io/docs/concepts/...`)
3. **Testability** — You can verify answers against the official docs

## How to Obtain

The corpus is obtained by cloning the Kubernetes website repository:

```bash
# Shallow clone (faster, smaller)
git clone --depth 1 https://github.com/kubernetes/website.git corpus/kubernetes-website
```

The documentation lives under `corpus/kubernetes-website/content/en/docs/`.

## Version / Snapshot

- **Path**: `corpus/kubernetes-website/content/en/docs/`
- **Commit**: `0a2c95c60f8cf6077c377a4f1324dcd7e41dbc51`
