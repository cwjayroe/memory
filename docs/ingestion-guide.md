# Ingestion Guide

## Chunking Modes

Files are split into chunks before storage. The chunking mode determines how that split happens. The `chunk_file()` function in `chunking.py` dispatches to the appropriate chunker based on mode and file extension.

| Mode | Best For | Behavior |
|------|----------|----------|
| `raw` | Any text | Sliding window at `MAX_CHARS=3200` with `overlap=320` characters. Simple and reliable. |
| `text` | Prose documents | Block-level chunking that preserves sentence boundaries. Better for narrative text. |
| `headings` | Markdown files | Splits on `#` headings. Each section becomes a chunk with the heading as context. |
| `python` | Python source | Extracts docstrings and function-level code blocks. Preserves structural context. |
| `mixed` | Full repositories | Per-extension auto-selection: `.py` → python docstrings, `.md` → headings, other text → text blocks. **Recommended for repo ingestion.** |
| `pdf` (auto) | PDF files | Always applied to `.pdf` files regardless of mode flag. Page-aware with structured block extraction. |

### Chunking Parameters

- `MAX_CHARS`: 3200 characters per chunk (raw and fallback modes)
- `OVERLAP_CHARS`: 320 characters of overlap between consecutive chunks (preserves context across chunk boundaries)
- PDF chunks use page provenance labels: `path/to/file.pdf::page-7::chunk-2`

### Python Chunking Detail

The `python` mode runs two passes:
1. **`chunk_python_docstrings`**: Extracts module, class, and function docstrings with their signatures
2. **`chunk_python_code`**: Extracts function and class bodies as code-level chunks

This produces semantically meaningful chunks instead of arbitrary character windows, making Python source searchable by functionality.

---

## CLI Subcommands

All commands are invoked via `python ingest.py <subcommand> [options]`. Run `python ingest.py --help` or `python ingest.py <subcommand> --help` for full flag reference.

### `project-init` — Create or Update a Scope Entry

Creates or updates a project entry in `projects.yaml`. Use this to bootstrap a new scope before ingesting into it.

```bash
python ingest.py project-init \
  --project billing-domain \
  --repos billing-api,worker-jobs \
  --description "Cross-repo context for the billing subsystem" \
  --tags billing,payments,invoices \
  --set-repo-defaults
```

`--set-repo-defaults`: Updates each named repo's `default_active_project` to point to this project.

---

### `repo` — Ingest an Entire Repository

Traverses the repo root, applies include/exclude globs from the manifest, chunks each file, and stores the results. Existing chunks for re-ingested files are replaced.

```bash
python ingest.py repo \
  --project billing-domain \
  --repo billing-api \
  --mode mixed
```

**Flags**:
- `--mode`: Chunking mode (default `mixed`)
- `--tags`: Additional tags to merge with manifest defaults
- `--manifest`: Override manifest path

---

### `file` — Ingest a Single File

Ingests one file. Useful for targeted updates without re-ingesting the whole repo.

```bash
python ingest.py file \
  --project migration-2026 \
  --repo worker-docs \
  --path ./docs/cutover-checklist.md \
  --mode headings \
  --tags cutover,checklist
```

**Notes**:
- `--path` accepts absolute or home-relative paths
- Existing chunks for the same `source_path` are deleted before storing new ones
- Repo `default_tags` from the manifest are merged with `--tags`

---

### `note` — Capture an Ad-Hoc Note

Stores a free-text note directly without a source file. Use for decisions, recaps, or any durable context not tied to a file.

```bash
python ingest.py note \
  --project customer-escalation-acme \
  --repo support-playbooks \
  --category decision \
  --source-kind summary \
  --text "Escalations touching invoice replay must validate ledger lag before manual re-run."
```

**Categories**: `decision`, `architecture`, `summary`, `code`, `documentation` (affects retention policy and ranking priority)

**Source kinds**: `summary`, `doc`, `code`, `note`

---

### `list` — Browse Stored Memories

Lists memories for a scope with optional filters. Useful for auditing what's stored.

```bash
python ingest.py list \
  --project billing-domain \
  --repo billing-api \
  --category decision \
  --limit 20
```

---

### `prune` — Remove Duplicates and Stale Entries

Removes:
- **Fingerprint duplicates**: Multiple stored memories with identical content hashes
- **Stale path entries**: Memories whose `source_path` no longer exists on disk

```bash
python ingest.py prune \
  --project billing-domain \
  --repo billing-api \
  --by both
```

`--by` options: `fingerprint`, `path`, `both` (default: `both`)

---

### `clear` — Delete All Memories for a Scope

Permanently deletes all memories in a scope. Cannot be undone. Prompts for confirmation.

```bash
python ingest.py clear \
  --project customer-escalation-acme
```

---

### `export` — Export to NDJSON

Dumps all memories for a scope to newline-delimited JSON. Used for backup or cross-machine migration.

```bash
python ingest.py export \
  --project billing-domain \
  --output ./backup.ndjson
```

Omit `--output` to write to stdout.

---

### `import` — Load from NDJSON

Loads memories from an NDJSON file. Upserts by default (existing memories with matching keys are updated).

```bash
python ingest.py import \
  --project migration-2026 \
  --file ./backup.ndjson
```

`--upsert` is the default behavior. Pass `--no-upsert` to skip existing memories instead of updating them.

---

### `watch` — Auto-Ingest on File Changes

Monitors a directory for file changes and automatically re-ingests modified files. Uses the manifest for repo config.

```bash
python ingest.py watch \
  --project billing-domain \
  --repo billing-api \
  --root /path/to/billing-api \
  --include "*.py,*.md" \
  --exclude "*.pyc" \
  --debounce 3.0
```

`--debounce`: Seconds to wait after a file change before ingesting (default 3.0). Prevents rapid re-ingestion during active editing.

File event filtering:
- Only `modified` and `created` events trigger ingestion
- `deleted` events trigger removal of the file's stored chunks
- Excluded patterns are checked before ingestion

---

### `context-plan` — Preview Layered Retrieval

Shows what queries would be issued for each layer of a context pack, and the resolved scopes for each layer. Does not execute searches.

```bash
python ingest.py context-plan \
  --repo billing-api
```

Useful for debugging manifest configuration and verifying scope resolution before a conversation.

---

### `policy-run` — Apply Retention Policy

Runs the three-tier retention policy against a scope.

```bash
# Preview (dry run with details)
python ingest.py policy-run \
  --project migration-2026 \
  --mode dry-run \
  --verbose

# Apply
python ingest.py policy-run \
  --project migration-2026 \
  --mode apply
```

**Flags**:
- `--mode`: `dry-run` (default) or `apply`
- `--verbose`: In dry-run, shows per-memory details (excerpt, reason, age) for each deletion candidate
- `--stale-days`: Age threshold for Tier C pruning (default 45)
- `--summary-keep`: Maximum summaries per `(repo, topic key)` for Tier B (default 5)

---

## Retention Policy Tiers

| Tier | Categories | Rule |
|------|-----------|------|
| **A — Protected** | `decision`, `architecture` | Never auto-pruned. These represent durable knowledge worth keeping indefinitely. |
| **B — Capped** | `summary` | At most `summary_keep` (default 5) summaries per `(repo, topic key)` pair. Oldest are pruned first. |
| **C — Age/Dedup** | `code`, `documentation` | Pruned if: (a) duplicate fingerprint exists, or (b) older than `stale_days` (default 45) and source path no longer exists. |

Run `policy-run --mode dry-run --verbose` before `apply` to review what would be deleted.

---

## Deduplication

Every stored chunk carries a **fingerprint** (SHA256 hash of normalized content). On storage:

1. The fingerprint is computed before any store attempt
2. If a memory with the same fingerprint already exists in the scope, the store is skipped and the existing ID is returned
3. The dedup check is per-scope: identical content in different scopes is stored independently

**Re-ingesting a file**: The system deletes existing chunks by `source_path` before storing new ones. This means edits are correctly reflected even if the fingerprint changes.

**Manual dedup**: Run `prune --by fingerprint` to clean up any duplicates that bypass the per-store check (e.g., created via different ingestion paths).

---

## PDF Ingestion

PDFs use a dedicated chunker (`chunk_pdf_document` in `chunking.py`) that runs automatically for `.pdf` files regardless of the `--mode` flag.

### How PDF Chunking Works

1. Each page is extracted via `pypdf`
2. Page text is split into structured blocks (paragraphs, headings where detectable)
3. Blocks are merged into chunks respecting `MAX_CHARS` with page provenance labels

### Stored Metadata

| Field | Value |
|-------|-------|
| `source_kind` | `doc` |
| `category` | `documentation` |
| Chunk label format | `path/to/file.pdf::page-1::chunk-2` |

### No-Text PDFs

If a PDF page has no extractable text (scanned/image-only), the chunker stores a placeholder `documentation` chunk noting the page number rather than silently skipping it. This ensures the file is represented in the scope even if content is not searchable.

### Re-ingestion

Chunking logic changes are not retroactively applied to stored chunks. After updating the chunker or if chunk boundaries look wrong, re-ingest the affected PDF:

```bash
python ingest.py file \
  --project my-project \
  --repo product-docs \
  --path ./docs/my-document.pdf
```

This deletes existing chunks for that `source_path` and stores fresh ones.
