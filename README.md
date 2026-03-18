# Project Memory

A local scoped memory and context system for agent workflows (Codex, Cursor, Claude). Combines an MCP server for retrieval and CRUD with a CLI for repo ingestion and manifest management. Uses a hybrid vector + SQLite backend for semantic search, structured metadata, entity graphs, and audit logging.

## Table of Contents

- [Quick Start](#quick-start)
- [What it supports](#what-it-supports)
- [Example scope shapes](#example-scope-shapes)
- [Documentation](#documentation)
- [Repo layout](#repo-layout)
- [Install](#install)
- [Run tests](#run-tests)
- [Manifest model](#manifest-model)
- [MCP server](#mcp-server)
- [Runtime configuration](#runtime-configuration)
- [CLI workflows](#cli-workflows)
- [PDF ingestion](#pdf-ingestion)
- [Retention policy](#retention-policy)
- [Codex skill](#codex-skill)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Clone and install dependencies
git clone <repo-url>
cd memory
python -m pip install -r requirements.txt

# 2. Start Ollama (required for embeddings and LLM operations)
ollama serve
ollama pull llama3.2

# 3. Set your primary scope
export PROJECT_ID=my-project

# 4. (Optional) Set storage root — defaults to ~/.project-memory
export PROJECT_MEMORY_ROOT=~/.project-memory

# 5. Start the MCP server
python mcp_server.py

# 6. Verify everything is working
python examples.py
```

To ingest your first repo, edit `projects.yaml` to add your project and repo, then:

```bash
python ingest.py project-init \
  --project my-project \
  --repos my-repo \
  --description "My project context"

python ingest.py repo \
  --project my-project \
  --repo my-repo \
  --mode mixed
```

See [docs/ingestion-guide.md](docs/ingestion-guide.md) for full ingestion documentation.

---

## What it supports

- scoped memories keyed by `project_id`
- many repos per scope through a manifest (`projects.yaml`)
- layered context preload and query-centered retrieval with optional exact-body follow-up
- repo/file ingestion, pruning, manifest bootstrap, and retention-policy runs

## Example scope shapes

- `engineering-standards`: shared coding and architecture guidance
- `billing-domain`: cross-repo context for a subsystem or business area
- `migration-2026`: initiative or workstream context spanning many repos
- `customer-escalation-acme`: incident or customer-specific context bundle

## Documentation

Detailed documentation lives in the `docs/` directory:


| Document                                                   | Contents                                                                               |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| [docs/architecture.md](docs/architecture.md)               | System architecture, component map, data flow diagrams, design decisions               |
| [docs/mcp-tools-reference.md](docs/mcp-tools-reference.md) | Full parameter reference for all 30 MCP tools with examples                            |
| [docs/configuration.md](docs/configuration.md)             | All environment variables, manifest schema reference, scope resolution walkthrough     |
| [docs/scoring-and-ranking.md](docs/scoring-and-ranking.md) | Hybrid scoring formula, ranking modes, candidate packing, tuning guide                 |
| [docs/ingestion-guide.md](docs/ingestion-guide.md)         | Chunking modes, all CLI subcommands, deduplication, watch mode, retention policy tiers |
| [docs/troubleshooting.md](docs/troubleshooting.md)         | Common errors, health check guide, debugging techniques                                |


---

## Repo layout

- `mcp_server.py`: MCP server exposing retrieval, CRUD, and maintenance tools
- `ingest.py`: CLI for ingest, note capture, pruning, manifest updates, and policy runs
- `memory_types.py`: typed request and namespace parsing models
- `helpers.py`: normalization, mem0 config wiring, inference helpers, and payload conversion
- `memory_manager.py`: memory lifecycle, search orchestration, caching, and CRUD behavior
- `manifest.py`: manifest v2 migration, repo resolution, and context-plan helpers
- `chunking.py`: text and PDF chunking logic
- `formatting.py`: text/json response formatting
- `scoring.py`: ranking, reranking, dedupe, and candidate packing
- `server_config.py`: environment-driven MCP configuration
- `health.py`: health-check utilities (Ollama, Chroma, embedding model, reranker) used by the `health_check` MCP tool
- `projects.yaml`: manifest v2 source of truth
- `skills/project-memory/SKILL.md`: Codex skill for preload and capture workflows

## Install

Create or activate a Python environment, then install dependencies from repo root:

```bash
python -m pip install -r requirements.txt
```

Important runtime dependencies:

- `ollama`: used for the mem0 LLM config
- `chromadb`: vector store backing mem0
- `pypdf`: required for PDF ingestion
- transformer/reranker packages: used by the search reranker pipeline

## Run tests

Run the suite from repo root:

```bash
python -m pytest -q
```

Optional coverage run:

```bash
mkdir -p .artifacts/coverage
COVERAGE_FILE=.artifacts/coverage/.coverage \
python -m pytest -q tests \
  --cov=. \
  --cov-report=term-missing \
  --cov-report=json:.artifacts/coverage/coverage.json \
  --cov-report=xml:.artifacts/coverage/coverage.xml \
  --cov-report=html:.artifacts/coverage/html
```

Coverage uses [.coveragerc](.coveragerc) when you run `pytest` with `--cov`; it sets `fail_under = 70`, omits `tests/`, `.artifacts/`, `skills/`, `.venv/`, and writes html/json/xml under `.artifacts/coverage/`. You can also run `python -m pytest -q --cov=. --cov-report=term-missing` and rely on `.coveragerc` for other options.

### Examples script

[examples.py](examples.py) spawns the MCP server as a subprocess and runs async examples (list tools, search_context, store/list/delete). Use it to sanity-check the server or as a reference for programmatic MCP usage:

```bash
python examples.py
```

## Manifest model

`projects.yaml` is the source of truth.

The current schema uses `projects`, `project_id`, and `default_active_project` as field names for compatibility. Those entries can still represent any context scope, not only software projects.

Top-level sections:

- `defaults`: ranking and preload defaults
- `projects`: scope metadata and associated repos, keyed by `project_id`
- `repos`: repo roots, include/exclude globs, default tags, and `default_active_project`
- `context_packs`: reusable preload definitions such as `default_3_layer`

Active-scope resolution generally follows:

1. explicit override
2. repo `default_active_project`
3. `PROJECT_ID` env fallback

## MCP server

The MCP server lives in `mcp_server.py` and registers as `memory`.

Run it directly from repo root:

```bash
python mcp_server.py
```

### MCP tools

- `search_context`
- `store_memory`
- `list_memories`
- `get_memory`
- `delete_memory`
- `ingest_repo`
- `ingest_file`
- `context_plan`
- `prune_memories`
- `init_project`
- `policy_run`
- `clear_memories`

### Additional MCP tools

- `update_memory`: update an existing memory's body and/or metadata (patch semantics; supply only fields to change). Required: `memory_id`; optional: `body`, `repo`, `source_path`, `source_kind`, `category`, `module`, `tags`, `priority`.
- `find_similar`: find memories semantically similar to a given text or an existing memory ID (for dedup review or related-context discovery). Optional: `project_id`, `memory_id`, `text`, `limit`, `threshold`, `response_format`. Provide either `memory_id` or `text`.
- `bulk_store`: store multiple memories in one call; returns per-item success/error. Required: `memories` (array of objects with `content`); optional: `project_id`. Each item can include `repo`, `source_path`, `source_kind`, `category`, `module`, `tags`, `upsert_key`, `fingerprint`, `priority`.
- `get_stats`: aggregate statistics for a scope (total count, breakdown by category/repo/source_kind/priority, oldest/newest timestamps, estimated token coverage). Optional: `project_id`, `repo`.
- `health_check`: check connectivity and readiness of Ollama, Chroma, embedding model, and reranker. Optional: `skip_slow` (skip slow model-load checks).
- `move_memory`: move one memory from one scope to another (re-store under target, delete from source). Required: `memory_id`, `target_project_id`; optional: `project_id` (source scope).
- `copy_scope`: copy all memories from one scope to another. Required: `from_project_id`, `to_project_id`. Optional: `dry_run` (preview without writing).
- `export_scope`: export all memories for a scope as a JSON array or newline-delimited JSON (backup or cross-machine migration). Optional: `project_id`, `format` (`json` or `ndjson`).
- `summarize_scope`: generate a prose summary of scope contents (grouped by category) using the configured LLM. Optional: `project_id`, `repo`, `category`, `max_tokens`.

### Graph and entity tools

These tools require `PROJECT_MEMORY_SQLITE_ENABLED=true` (default). They operate on the knowledge graph stored in SQLite.

- `link_memories`: create a typed relation between two memories. Required: `source_id`, `target_id`. Optional: `relation` (`supersedes`, `implements`, `depends_on`, `related_to`, `contradicts`, `refines`; default `related_to`), `project_id`, `confidence` (0.0–1.0).
- `get_related`: traverse memory relations by hop count. Required: `memory_id`. Optional: `project_id`, `max_hops` (1–3), `relation_types`, `response_format`.
- `list_entities`: enumerate extracted entities for a scope. Optional: `project_id`, `kind` (`service`, `api`, `module`, `pattern`, `concept`, `tool`, `file`), `limit`, `response_format`.
- `search_by_entity`: retrieve all memories linked to a named entity. Required: `entity_name`. Optional: `entity_kind`, `project_id`, `response_format`.
- `get_memory_history`: view version history for a memory. Required: `memory_id`. Optional: `project_id`, `response_format`.
- `extract_entities`: run entity extraction over a scope or a single memory; builds and updates the knowledge graph. Optional: `project_id`, `memory_id` (omit to process all memories in scope).
- `migrate_to_sqlite`: backfill SQLite metadata from the ChromaDB vector store. Run once when enabling SQLite on an existing deployment. Optional: `project_id`.
- `consolidate_memories`: cluster and propose merges for related memories sharing entities. Optional: `project_id`, `category`, `entity`, `dry_run` (default `true`).
- `detect_duplicates`: find near-duplicate memory groups using text similarity. Optional: `project_id`, `threshold` (default 0.92), `category`, `response_format`.

For full parameter tables and usage examples for all 30 tools, see [docs/mcp-tools-reference.md](docs/mcp-tools-reference.md).

### Project stats (`get_stats`)

Use the `get_stats` MCP tool to inspect a scope without running search or embeddings. Arguments: `project_id` (optional; defaults to configured scope), `repo` (optional filter). The response is JSON with: `total_memories`, `estimated_tokens`, `oldest_updated_at`, `newest_updated_at`, `duplicate_fingerprints`, and breakdowns `by_category`, `by_repo`, `by_source_kind`, `by_priority`. Useful for audits and capacity checks.

### `search_context`

Required:

- `query`

Scope:

- `project_id`: explicit single-scope selector; this is the current interface name
- `project_ids`: explicit multi-scope selector; this is the current interface name
- if omitted, scope is inferred from query text plus manifest metadata

Filters:

- `repo`
- `path_prefix`
- `tags`
- `categories`
- `after_date`, `before_date`: ISO 8601 datetime; only return memories updated in that range
- `highlight`: wrap matching query tokens in **bold** in excerpt text
- `search_all_scopes`: search across all manifest scopes (ignores `project_id` / `project_ids`)

Ranking controls:

- `ranking_mode`: `hybrid_weighted_rerank` or `hybrid_weighted`
- `token_budget`
- `candidate_pool`
- `rerank_top_n`
- `limit`
- `debug`

Response controls:

- `response_format`: `text` or `json`
- `include_full_text`: include full selected bodies in json/text responses when supported
- `excerpt_chars`: excerpt size clamp for text-oriented payloads

Search behavior:

- text responses are concise and query-centered, not raw prefix dumps
- response headers include `scope_source` and `resolved_projects`
- if inferred scope returns no results, the server retries once with `PROJECT_ID + org_practice_projects`
- use `response_format="json"` when you need stable IDs, excerpts, or excerpt metadata
- use `get_memory` after search when you need the full untruncated body for one result

### `list_memories` and `get_memory`

- `list_memories` supports `response_format`, `include_full_text`, and `excerpt_chars`; and `sort_by` (e.g. `updated_at`, `created_at`, `category`, `repo`) and `sort_order` (`asc` / `desc`)
- default list output is excerpted/snippet-oriented
- `get_memory` is the exact-read endpoint for one `memory_id`
- `get_memory` returns the full stored body in both text and json modes

### `store_memory`

- In addition to the fields in the tool list, `store_memory` supports `priority` (high/normal/low; affects ranking weight) and `suggest_tags` (return suggested tags extracted from the body).

### Maintenance tools

The MCP server also exposes maintenance operations for repo workflows:

- `ingest_repo`: ingest all files for a manifest-backed repo profile
- `ingest_file`: ingest one file and merge manifest-backed repo default tags
- `context_plan`: preview the resolved layered context payloads for a repo
- `prune_memories`: remove duplicate fingerprints and/or stale missing-path items in a selected scope
- `init_project`: create or update a manifest scope entry using the current `project` field name, with optional `set_repo_defaults`
- `policy_run`: preview or apply the retention policy through MCP; use `verbose=true` in dry-run to show per-memory deletion details (excerpt, reason, age)
- `clear_memories`: delete all memories for a selected scope after explicit confirmation

## Runtime configuration

Environment variables currently used by the repo:

Core/project defaults:

- `PROJECT_ID`: fallback scope key when explicit or inferred scope is unavailable
- `PROJECT_MEMORY_ROOT`: local storage root for per-scope Chroma collections
- `PROJECT_MEMORY_GET_ALL_LIMIT`: max item count used for broad list/get-all operations

Manifest and inference:

- `PROJECT_MEMORY_MANIFEST_PATH`: manifest path; defaults to repo-local `projects.yaml`
- `PROJECT_MEMORY_MAX_PROJECTS`: maximum projects per search request
- `PROJECT_MEMORY_INFERENCE_MAX_PROJECTS`: cap for inferred project candidates

Ranking and reranking:

- `PROJECT_MEMORY_RANKING_MODE`
- `PROJECT_MEMORY_DEFAULT_TOKEN_BUDGET`
- `PROJECT_MEMORY_MIN_TOKEN_BUDGET`
- `PROJECT_MEMORY_MAX_TOKEN_BUDGET`
- `PROJECT_MEMORY_DEFAULT_RERANK_TOP_N`
- `PROJECT_MEMORY_MAX_CANDIDATE_POOL`
- `PROJECT_MEMORY_RERANKER_MODEL`

Timeouts and cache:

- `PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS`
- `PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS`
- `PROJECT_MEMORY_CACHE_TTL_SECONDS`
- `PROJECT_MEMORY_CACHE_MAX_ENTRIES`

mem0/Ollama wiring:

- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`

## CLI workflows

The documented CLI path is direct script invocation from repo root:

```bash
python ingest.py --help
```

### Common commands

The examples below are illustrative. Replace scope IDs such as `engineering-standards`, `billing-domain`, `migration-2026`, and `customer-escalation-acme` with your own `project_id` values.

Create or update a scope entry in the manifest (`--project` is the current CLI flag name):

```bash
python ingest.py project-init \
  --project engineering-standards \
  --repos billing-api,worker-docs \
  --description "Shared engineering and architecture guidance" \
  --tags standards,architecture \
  --set-repo-defaults
```

Preview the resolved 3-layer preload plan for a repo:

```bash
python ingest.py context-plan \
  --repo billing-api
```

Preview retention policy effects (use `--verbose` in dry-run to show per-memory deletion details):

```bash
python ingest.py policy-run \
  --project migration-2026 \
  --mode dry-run \
  --verbose
```

Apply the retention policy:

```bash
python ingest.py policy-run \
  --project migration-2026 \
  --mode apply
```

Ingest an entire repo into a scope:

```bash
python ingest.py repo \
  --project billing-domain \
  --repo billing-api \
  --mode mixed
```

Ingest a single file into a scope:

```bash
python ingest.py file \
  --project migration-2026 \
  --repo worker-docs \
  --manifest ./projects.yaml \
  --path ./docs/cutover-checklist.md \
  --mode mixed
```

Store a decision or recap in a scope:

```bash
python ingest.py note \
  --project customer-escalation-acme \
  --repo support-playbooks \
  --category decision \
  --source-kind summary \
  --text "Escalations touching invoice replay must validate ledger lag before manual re-run."
```

List memories:

```bash
python ingest.py list \
  --project engineering-standards \
  --repo billing-api \
  --limit 20
```

Prune duplicates and stale missing-path entries:

```bash
python ingest.py prune \
  --project billing-domain \
  --repo billing-api \
  --by both
```

Clear all memories for a scope:

```bash
python ingest.py clear \
  --project customer-escalation-acme
```

### Export, import, and watch

Export all memories for a scope to newline-delimited JSON (default: stdout; use `--output` to write to a file):

```bash
python ingest.py export \
  --project billing-domain \
  --output ./backup.ndjson
```

Import memories from an NDJSON file into a scope (existing memories with matching keys are upserted when `--upsert` is set, which is the default):

```bash
python ingest.py import \
  --project migration-2026 \
  --file ./backup.ndjson
```

Watch a directory and auto-ingest changed files (uses manifest-backed repo config; `--debounce` defaults to 3 seconds):

```bash
python ingest.py watch \
  --project billing-domain \
  --repo billing-api \
  --root /path/to/repo \
  --include "*.py,*.md" \
  --exclude "*.pyc" \
  --debounce 3.0
```

## PDF ingestion

- PDFs require `pypdf`
- PDF text is chunked with page provenance and structured boundaries before raw character chunking
- stored PDF chunks keep labels such as `page-7::chunk-2`
- re-ingest affected PDFs after chunking changes; existing stored chunks are not rewritten automatically

### Ingest a single PDF

If your manifest includes a repo profile for documents, ingest the PDF through that repo. This repo already includes a `product-docs` profile in `projects.yaml`; in your own setup, that profile can support any scope shape.

```bash
python ingest.py file \
  --project customer-escalation-acme \
  --repo product-docs \
  --manifest ./projects.yaml \
  --path "/Users/willjayroe/Downloads/ACME Escalation Timeline.pdf" \
  --mode headings \
  --tags incident,customer
```

Notes:

- the CLI still accepts `--mode`, but `.pdf` files always use the PDF-specific chunker
- repo `default_tags` are merged with the tags you pass; for `product-docs` that means `product-docs` and `prd` are added automatically
- existing chunks for the same source path are deleted before the PDF is re-ingested

### Ingest all PDFs from a manifest-backed docs repo

If you want to ingest every matching file from the repo profile root:

```bash
python ingest.py repo \
  --project migration-2026 \
  --repo product-docs \
  --mode headings
```

The `product-docs` profile currently includes `**/*.pdf`, `**/*.md`, `**/*.rst`, and `**/*.txt`, so this will ingest all matching documents under that configured root.

### What gets stored

- each PDF page is split into structured blocks before chunking
- stored chunks use `source_kind="doc"` and `category="documentation"`
- each chunk records page provenance in labels like `path/to/file.pdf::page-1::chunk-2`
- if a PDF has no extractable text, ingestion stores a placeholder documentation chunk instead of silently skipping the file

## Retention policy

`policy-run` currently applies three broad rules:

- Tier A: `decision` and `architecture` are protected from auto-prune
- Tier B: `summary` items are capped per `(repo, topic key)` by `summary_keep`
- Tier C: `code` and `documentation` items can be pruned by duplicate fingerprint and age

## Codex skill

Use `skills/project-memory/SKILL.md` for conversation startup, context preload, and durable decision capture.

The skill is MCP-only. Use the CLI or explicit maintenance MCP tools when you need repo ingestion or manifest maintenance.

The AGENTS snippet lives in `skills/project-memory/references/agents-snippet.md`.

## Debugging

For quick local debugging, run the server directly:

```bash
python mcp_server.py
```

For debugger attach flows, use repo-local paths instead of machine-specific absolute paths. Example:

```bash
python -m debugpy --listen 5678 --wait-for-client ./mcp_server.py
```

Then attach your IDE debugger to `127.0.0.1:5678`.

If you want to script MCP calls against the local server, point your client at repo-local entrypoints such as `./mcp_server.py` and set `PROJECT_ID` in the spawned environment.

## Troubleshooting

- If a relevant stored rule does not appear in text mode, retry with `response_format="json"` and inspect result IDs plus excerpt metadata.
- If you need the exact stored body for one result, call `get_memory` with the returned `memory_id`.
- If a PDF-derived result looks too broad or too old, re-ingest the source PDF so the current chunker replaces older stored chunks.
- If reranking is unavailable, inspect the configured reranker dependencies and `PROJECT_MEMORY_RERANKER_MODEL`.

For a full diagnostics guide including health-check commands, common error messages, Ollama/ChromaDB/SQLite failure modes, and debugging flows, see [docs/troubleshooting.md](docs/troubleshooting.md).