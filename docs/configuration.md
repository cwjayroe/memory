# Configuration Reference

## Environment Variables

All configuration is read at startup via `server_config.py`. No restart is required for manifest changes (the manifest is re-read per request), but env var changes require a server restart.

### Core / Project Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_ID` | `project-memory-default` | Fallback scope key when no explicit or inferred scope is available. Set this to your primary project name. |
| `PROJECT_MEMORY_ROOT` | `~/.project-memory` | Local storage root for per-scope ChromaDB collections and the SQLite database. Each scope gets its own subdirectory. |
| `PROJECT_MEMORY_GET_ALL_LIMIT` | `1000` | Maximum item count for broad list/get-all operations. Prevents runaway queries on large scopes. |

### Manifest and Inference

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_MEMORY_MANIFEST_PATH` | `./projects.yaml` (repo-local) | Path to the manifest file. Supports `~` expansion. Override when the manifest lives outside the repo. |
| `PROJECT_MEMORY_MAX_PROJECTS` | `10` | Maximum number of projects that can be searched in a single request (multi-scope cap). |
| `PROJECT_MEMORY_INFERENCE_MAX_PROJECTS` | `2` | Maximum number of projects returned by query-text inference. Capped by `PROJECT_MEMORY_MAX_PROJECTS`. |

### Ranking and Reranking

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_MEMORY_RANKING_MODE` | `hybrid_weighted_rerank` | Search ranking strategy. Options: `hybrid_weighted_rerank` (uses cross-encoder reranker), `hybrid_weighted` (no reranker, faster). |
| `PROJECT_MEMORY_MIN_TOKEN_BUDGET` | `600` | Minimum allowed token budget for search results (default: 600). |
| `PROJECT_MEMORY_MAX_TOKEN_BUDGET` | `4000` | Maximum allowed token budget for search results (default: 4000). |
| `PROJECT_MEMORY_DEFAULT_TOKEN_BUDGET` | `1800` | Default token budget when not specified (default: 1800). |
| `PROJECT_MEMORY_DEFAULT_RERANK_TOP_N` | `40` | Number of candidates passed to the cross-encoder reranker. Higher = better precision, slower. |
| `PROJECT_MEMORY_MAX_CANDIDATE_POOL` | `200` | Maximum candidate pool size from vector search before scoring. |
| `PROJECT_MEMORY_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | HuggingFace model ID for the cross-encoder reranker. Downloaded on first use. |

### Timeouts and Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS` | `8.0` | Per-project search timeout. If a scope times out, results from other scopes are still returned. |
| `PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS` | `20.0` | Total search timeout across all scopes for a single query. |
| `PROJECT_MEMORY_CACHE_TTL_SECONDS` | `60` | Search result cache TTL in seconds. Identical queries within this window return cached results instantly. |
| `PROJECT_MEMORY_CACHE_MAX_ENTRIES` | `128` | Maximum number of entries in the in-memory search cache. LRU eviction when exceeded. |

### SQLite

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_MEMORY_SQLITE_ENABLED` | `true` | Enable the SQLite metadata layer. Disable only if debugging the vector store in isolation. Accepts `1`, `true`, `yes`. |
| `PROJECT_MEMORY_SQLITE_WAL` | `true` | Enable SQLite WAL (Write-Ahead Logging) mode. Improves concurrent read/write performance. |

### Ollama / LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL for the Ollama API. Change if Ollama runs on a different host or port. |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model used for LLM operations (scope summaries, mem0 inference). Must be pulled before use. |

---

## Performance Tuning by Scenario

| Scenario | Recommended Changes |
|----------|-------------------|
| **Fast responses, lower quality** | `PROJECT_MEMORY_RANKING_MODE=hybrid_weighted`, reduce `PROJECT_MEMORY_DEFAULT_RERANK_TOP_N` to 20 |
| **High-precision retrieval** | Increase `PROJECT_MEMORY_DEFAULT_RERANK_TOP_N` to 60-80, increase `PROJECT_MEMORY_MAX_CANDIDATE_POOL` to 300 |
| **Large token context window** | Increase `PROJECT_MEMORY_DEFAULT_TOKEN_BUDGET` to 3000-4000 |
| **Many concurrent searches** | Increase `PROJECT_MEMORY_CACHE_MAX_ENTRIES` to 256-512 |
| **Many large scopes** | Increase `PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS` to 15.0 |
| **Slow first search** | Pre-warm by running a test search at startup; models load lazily |

---

## Manifest Schema Reference (`projects.yaml`)

The manifest is the source of truth for project scope definitions, repo configurations, and context pack layouts. It is re-read on each request; no server restart is needed after edits.

### Full Annotated Example

```yaml
# Manifest format version. Always 2 for current installations.
version: 2

defaults:
  # Default ranking mode for all searches.
  # Options: hybrid_weighted_rerank | hybrid_weighted
  ranking_mode: hybrid_weighted_rerank

  # Default token budget for packed search results.
  token_budget: 1800

  # Default result limit per search request.
  limit: 6

  # Scopes searched as fallback when inferred scope returns no results.
  # Typically your org-wide practices/standards project.
  org_practice_projects:
    - engineering-standards

projects:
  # Key is the project_id (scope identifier). Can represent any context shape:
  # project, domain, initiative, incident, customer issue, standards pack, etc.
  engineering-standards:
    # Human-readable description. Used by query inference to match queries to scopes.
    description: Shared coding standards and architecture practices.

    # Tags used by query-text inference to route queries to this scope.
    # Include domain keywords, technology names, common query terms.
    tags:
      - standards
      - architecture
      - practices
      - patterns

    # Repo names (defined in the repos section below) associated with this scope.
    repos:
      - backend-services
      - frontend-app

  billing-domain:
    description: Cross-repo context for the billing subsystem.
    tags:
      - billing
      - payments
      - invoices
      - subscriptions
    repos:
      - billing-api
      - worker-jobs

  migration-2026:
    description: Initiative context for the 2026 database migration.
    tags:
      - migration
      - postgres
      - cutover
    repos:
      - billing-api
      - product-docs

repos:
  # Key is the repo name referenced from projects above and CLI --repo flag.
  billing-api:
    # Absolute path to the repo root on this machine.
    root: /path/to/repos/billing-api

    # Default scope for this repo when no project_id is specified.
    # Matches a key in the projects section above.
    default_active_project: billing-domain

    # Glob patterns to include during repo ingestion.
    # Relative to root.
    include:
      - '**/*.py'
      - '**/*.md'
      - '**/*.rst'

    # Glob patterns to exclude. Applied after include matching.
    exclude:
      - '**/.git/**'
      - '**/.venv/**'
      - '**/__pycache__/**'
      - '**/.pytest_cache/**'
      - '**/node_modules/**'
      - '**/migrations/**'    # skip auto-generated migration files

    # Tags automatically added to every memory ingested from this repo.
    # Merged with any tags passed explicitly during ingestion.
    default_tags:
      - billing-api

  product-docs:
    root: /path/to/downloads
    default_active_project: migration-2026
    include:
      - '**/*.pdf'
      - '**/*.md'
      - '**/*.rst'
      - '**/*.txt'
    exclude:
      - '**/.git/**'
    default_tags:
      - product-docs
      - prd

context_packs:
  # Named preload configurations. Referenced by context_plan and SKILL.md.
  default_3_layer:
    # Layer 1: org-wide practices. Always searched first.
    layer_1:
      query: engineering best practices, architecture constraints, coding standards
      # project_ids_from: resolve project IDs from this manifest key.
      # org_practice_projects → reads defaults.org_practice_projects.
      project_ids_from: org_practice_projects

    # Layer 2: active project context (decisions, constraints).
    layer_2:
      # {active_project} is substituted with the current repo's default_active_project.
      query_template: '{active_project} architecture, recent decisions, constraints'
      project_ids_from: '[active_project] + org_practice_projects'

    # Layer 3: repo-specific code and documentation context.
    layer_3:
      query_template: '{active_project} in repo {repo}, critical files and flow constraints'
      project_ids_from: '[active_project] + org_practice_projects'
      # Restrict results to the specific repo being worked in.
      repo_filter: true
      # Only return memories in these categories for layer 3.
      categories:
        - code
        - summary
        - decision
        - architecture
        - documentation
```

### Field Reference

#### `defaults`
| Field | Type | Description |
|-------|------|-------------|
| `ranking_mode` | string | Default ranking mode: `hybrid_weighted_rerank` or `hybrid_weighted` |
| `token_budget` | int | Default token budget for packed results |
| `limit` | int | Default result count per search |
| `org_practice_projects` | list[str] | Scopes used as fallback when primary scope returns no results |

#### `projects[key]`
| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Used by query inference to match queries to this scope |
| `tags` | list[str] | Keywords for query-text inference routing |
| `repos` | list[str] | Repo names (must exist in `repos` section) |

#### `repos[key]`
| Field | Type | Description |
|-------|------|-------------|
| `root` | string | Absolute filesystem path to repo root |
| `default_active_project` | string | Scope used when `project_id` is not specified |
| `include` | list[str] | Glob patterns to include during ingestion |
| `exclude` | list[str] | Glob patterns to exclude during ingestion |
| `default_tags` | list[str] | Tags merged into every memory stored from this repo |

#### `context_packs[key].layer_N`
| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Static query string for this layer |
| `query_template` | string | Template with `{active_project}` and `{repo}` substitution |
| `project_ids_from` | string | Expression: `org_practice_projects`, `[active_project]`, or combined |
| `repo_filter` | bool | If true, restrict results to the current repo |
| `categories` | list[str] | Filter results to specific memory categories |

---

## Scope Resolution Walkthrough

Given a request with `repo=billing-api` and no explicit `project_id`:

1. **Explicit override**: no `project_id` provided → skip
2. **Manifest repo default**: `repos.billing-api.default_active_project = billing-domain` → use `billing-domain`
3. If `billing-domain` returns no results, retry with `billing-domain + engineering-standards` (org_practice_projects)
4. If still empty, fall back to `PROJECT_ID` env var

Given a request with `query="payment retry logic"` and no repo or project:

1. **Explicit override**: no `project_id` → skip
2. **No repo default**: no repo specified → skip
3. **Inference**: tokenize `"payment retry logic"` → tokens `["payment", "retry", "logic"]`
   - `billing-domain` has tags `["billing", "payments", "invoices"]` → match on "payment"
   - `engineering-standards` has tags `["standards", "architecture", "practices"]` → no match
   - Result: infer `billing-domain`
4. If empty, retry with `billing-domain + engineering-standards`
