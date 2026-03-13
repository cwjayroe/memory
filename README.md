# Project Memory

This repo provides a local scoped memory and context system for agent workflows in tools such as Codex, Cursor, and Claude. It combines an MCP server for retrieval and CRUD operations with a small ingestion CLI for repo maintenance and manifest management.

The implementation currently uses `project_id` as the storage and retrieval namespace key. In practice, a `project_id` can represent a project, domain, workstream, standards pack, migration, incident, customer issue, or any other durable context scope.

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
- `list_memories` supports `response_format`, `include_full_text`, and `excerpt_chars`
- default list output is excerpted/snippet-oriented
- `get_memory` is the exact-read endpoint for one `memory_id`
- `get_memory` returns the full stored body in both text and json modes

### Maintenance tools
The MCP server also exposes maintenance operations for repo workflows:
- `ingest_repo`: ingest all files for a manifest-backed repo profile
- `ingest_file`: ingest one file and merge manifest-backed repo default tags
- `context_plan`: preview the resolved layered context payloads for a repo
- `prune_memories`: remove duplicate fingerprints and/or stale missing-path items in a selected scope
- `init_project`: create or update a manifest scope entry using the current `project` field name, with optional `set_repo_defaults`
- `policy_run`: preview or apply the retention policy through MCP
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

Preview retention policy effects:

```bash
python ingest.py policy-run \
  --project migration-2026 \
  --mode dry-run
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
