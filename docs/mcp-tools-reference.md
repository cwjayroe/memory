# MCP Tools Reference

The MCP server (`mcp_server.py`) registers 30 tools under the `memory` server name. All tools accept JSON arguments and return text content.

---

## Search and Retrieval

### `search_context`

Search scoped memory for architectural context, decisions, and code-aware summaries.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | — | Natural language search query |
| `project_id` | No | string | inferred | Single scope to search |
| `project_ids` | No | array/string | inferred | Multiple scopes to search |
| `repo` | No | string | — | Filter results to a specific repo |
| `path_prefix` | No | string | — | Filter results to a source path prefix |
| `tags` | No | array/string | — | Filter results to memories with all specified tags |
| `categories` | No | array/string | — | Filter results to specified categories |
| `after_date` | No | string | — | ISO 8601 datetime — only results updated after this date |
| `before_date` | No | string | — | ISO 8601 datetime — only results updated before this date |
| `highlight` | No | boolean | false | Wrap matching query tokens in **bold** in excerpt text |
| `search_all_scopes` | No | boolean | false | Search across all manifest scopes (ignores `project_id`/`project_ids`) |
| `ranking_mode` | No | string | `hybrid_weighted_rerank` | `hybrid_weighted_rerank` or `hybrid_weighted` |
| `token_budget` | No | integer | 1800 | Max token count for packed results (minimum: 600, maximum: 4000, default: 1800) |
| `candidate_pool` | No | integer | 200 | Vector search candidate pool size |
| `rerank_top_n` | No | integer | 40 | Candidates passed to cross-encoder reranker |
| `limit` | No | integer | 8 | Max results to return |
| `debug` | No | boolean | false | Include per-result score breakdown in JSON response |
| `response_format` | No | string | `text` | `text` or `json` |
| `include_full_text` | No | boolean | false | Include full untruncated bodies in response |
| `excerpt_chars` | No | integer | 420 | Max chars per excerpt in text mode |

**Returns**: Text: query-centered excerpts with `scope_source` header. JSON: array of results with `id`, `excerpt`, `metadata`, `score`.

**Example**:
```json
{
  "tool": "search_context",
  "arguments": {
    "query": "payment retry logic and backoff strategy",
    "project_id": "billing-domain",
    "categories": ["decision", "architecture"],
    "limit": 5,
    "response_format": "json"
  }
}
```

---

### `find_similar`

Find memories semantically similar to a given text or an existing memory ID. Useful for dedup review and related-context discovery.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | No* | string | — | ID of seed memory (searches from its body) |
| `text` | No* | string | — | Raw text to find similar memories for |
| `project_id` | No | string | inferred | Scope to search |
| `limit` | No | integer | 10 | Max results |
| `threshold` | No | number | 0.0 | Minimum similarity score (0.0–1.0) |
| `response_format` | No | string | `text` | `text` or `json` |

*Provide either `memory_id` or `text`, not both.

**Example**:
```json
{
  "tool": "find_similar",
  "arguments": {
    "text": "Circuit breaker pattern for outbound API calls",
    "project_id": "billing-domain",
    "limit": 5,
    "threshold": 0.7
  }
}
```

---

### `get_memory`

Fetch a single stored memory by ID, including the full untruncated body.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | Yes | string | — | Memory ID to retrieve |
| `project_id` | No | string | inferred | Scope to search |
| `response_format` | No | string | `text` | `text` or `json` |

**Returns**: Full memory body plus metadata. Use this after `search_context` when you need the complete stored content.

**Example**:
```json
{
  "tool": "get_memory",
  "arguments": {
    "memory_id": "abc123def456"
  }
}
```

---

### `list_memories`

List stored memories for a scope with optional filters, pagination, and sort control.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope to list from |
| `repo` | No | string | — | Filter to a repo |
| `category` | No | string | — | Filter to a category |
| `tag` | No | string | — | Filter to a specific tag |
| `path_prefix` | No | string | — | Filter to a source path prefix |
| `offset` | No | integer | 0 | Pagination offset |
| `limit` | No | integer | 20 | Results per page |
| `sort_by` | No | string | `updated_at` | Sort field: `updated_at`, `created_at`, `category`, `repo` |
| `sort_order` | No | string | `desc` | `asc` or `desc` |
| `response_format` | No | string | `text` | `text` or `json` |
| `include_full_text` | No | boolean | false | Include full bodies instead of excerpts |
| `excerpt_chars` | No | integer | 420 | Max chars per excerpt |

**Example**:
```json
{
  "tool": "list_memories",
  "arguments": {
    "project_id": "billing-domain",
    "category": "decision",
    "sort_by": "updated_at",
    "limit": 10
  }
}
```

---

## CRUD Operations

### `store_memory`

Store structured memory in a scope.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `content` | Yes | string | — | Memory body text |
| `project_id` | No | string | inferred | Target scope |
| `repo` | No | string | — | Repo name for metadata |
| `source_path` | No | string | — | Source file path |
| `source_kind` | No | string | `summary` | `summary`, `doc`, `code`, `note` |
| `category` | No | string | — | `decision`, `architecture`, `summary`, `code`, `documentation` |
| `module` | No | string | — | Module or component name |
| `tags` | No | array/string | — | Tags for filtering and TF-IDF |
| `upsert_key` | No | string | — | If set, replaces any existing memory with the same key |
| `fingerprint` | No | string | — | Override the auto-computed fingerprint |
| `priority` | No | string | `normal` | `high` (+20% ranking boost), `normal`, `low` (-10% penalty) |
| `suggest_tags` | No | boolean | false | Return TF-IDF suggested tags extracted from the body |

**Returns**: `{memory_id, deleted_count, suggested_tags?}`

**Example**:
```json
{
  "tool": "store_memory",
  "arguments": {
    "content": "All payment retry logic must use exponential backoff with jitter. Max 3 retries. Log each attempt to the audit trail.",
    "project_id": "billing-domain",
    "repo": "billing-api",
    "category": "decision",
    "source_kind": "summary",
    "tags": ["payments", "retry", "resilience"],
    "priority": "high"
  }
}
```

---

### `update_memory`

Atomically update an existing memory's body and/or metadata. Patch semantics: only fields you supply are changed.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | Yes | string | — | ID of memory to update |
| `project_id` | No | string | inferred | Scope containing the memory |
| `body` | No | string | — | New body text (replaces existing) |
| `repo` | No | string | — | Update repo metadata |
| `source_path` | No | string | — | Update source path |
| `source_kind` | No | string | — | Update source kind |
| `category` | No | string | — | Update category |
| `module` | No | string | — | Update module |
| `tags` | No | array/string | — | Replace tags |
| `priority` | No | string | — | Update priority |

> **Note:** `update_memory` deletes the old memory and creates a new one, producing a new `memory_id`. The old ID becomes invalid after the update. Use the `new_id` returned in the response for subsequent operations. Version history is preserved and accessible via `get_memory_history` on the new ID.

**Example**:
```json
{
  "tool": "update_memory",
  "arguments": {
    "memory_id": "abc123",
    "body": "Updated: All payment retry logic must use exponential backoff with jitter. Max 5 retries (increased from 3).",
    "tags": ["payments", "retry", "resilience", "updated"]
  }
}
```

---

### `delete_memory`

Delete a memory by ID, or delete all memories matching an `upsert_key` within a scope.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | No* | string | — | ID of memory to delete |
| `upsert_key` | No* | string | — | Delete all memories with this upsert key |
| `project_id` | No | string | inferred | Scope to delete from |

*Provide either `memory_id` or `upsert_key`.

**Example**:
```json
{
  "tool": "delete_memory",
  "arguments": {
    "memory_id": "abc123def456",
    "project_id": "billing-domain"
  }
}
```

---

### `bulk_store`

Store multiple memories in a single call. Returns per-item success/error results.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memories` | Yes | array | — | Array of memory objects (see below) |
| `project_id` | No | string | inferred | Target scope for all memories |

Each memory object supports: `content` (required), `repo`, `source_path`, `source_kind`, `category`, `module`, `tags`, `upsert_key`, `fingerprint`, `priority`.

**Example**:
```json
{
  "tool": "bulk_store",
  "arguments": {
    "project_id": "billing-domain",
    "memories": [
      {
        "content": "Payment service uses idempotency keys for all charge operations.",
        "category": "architecture",
        "tags": ["payments", "idempotency"]
      },
      {
        "content": "Subscription renewal is handled by the worker-jobs service, not billing-api.",
        "category": "decision",
        "tags": ["subscriptions", "architecture"]
      }
    ]
  }
}
```

---

### `move_memory`

Move a single memory from one scope to another. Re-stores with updated `project_id` and deletes from source.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | Yes | string | — | ID of memory to move |
| `target_project_id` | Yes | string | — | Destination scope |
| `project_id` | No | string | inferred | Source scope |

**Example**:
```json
{
  "tool": "move_memory",
  "arguments": {
    "memory_id": "abc123",
    "project_id": "staging-scope",
    "target_project_id": "billing-domain"
  }
}
```

---

## Scope Management

### `init_project`

Initialize or update a scope entry in the memory manifest (`projects.yaml`).

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Scope key (project_id) to create or update |
| `repos` | Yes | array/string | — | Repo names to associate with this scope |
| `description` | No | string | — | Human-readable description (used by query inference) |
| `tags` | No | array/string | — | Tags for query inference |
| `set_repo_defaults` | No | boolean | false | Set each repo's `default_active_project` to this project |

**Example**:
```json
{
  "tool": "init_project",
  "arguments": {
    "project": "new-feature-x",
    "repos": ["billing-api", "worker-jobs"],
    "description": "Feature X implementation across billing and worker services",
    "tags": ["feature-x", "billing", "workers"],
    "set_repo_defaults": false
  }
}
```

---

### `copy_scope`

Copy all memories from one scope to another.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `from_project_id` | Yes | string | — | Source scope |
| `to_project_id` | Yes | string | — | Destination scope |
| `dry_run` | No | boolean | false | Preview without writing |

**Example**:
```json
{
  "tool": "copy_scope",
  "arguments": {
    "from_project_id": "billing-domain",
    "to_project_id": "billing-domain-backup",
    "dry_run": true
  }
}
```

---

### `export_scope`

Export all memories for a scope as JSON or newline-delimited JSON. Useful for backup or cross-machine migration.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope to export |
| `format` | No | string | `json` | `json` (array) or `ndjson` (one record per line) |

**Returns**: JSON array or NDJSON stream of memory objects.

**Example**:
```json
{
  "tool": "export_scope",
  "arguments": {
    "project_id": "billing-domain",
    "format": "ndjson"
  }
}
```

---

### `clear_memories`

Delete ALL memories for a selected scope. Requires `confirm=true` to proceed.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Scope to clear |
| `confirm` | No | boolean | false | Must be `true` to execute; returns warning prompt otherwise |

**Example**:
```json
{
  "tool": "clear_memories",
  "arguments": {
    "project": "temp-scratch-scope",
    "confirm": true
  }
}
```

---

## Maintenance

### `ingest_repo`

Ingest all files in a repository into scoped memory. Existing chunks for each file are replaced.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Target scope |
| `repo` | Yes | string | — | Repo name (must exist in manifest) |
| `root` | No | string | — | Override the repo root path from manifest |
| `include` | No | array/string | manifest defaults | Glob patterns to include |
| `exclude` | No | array/string | manifest defaults | Glob patterns to exclude |
| `mode` | No | string | `mixed` | Chunking mode: `mixed`, `headings`, `python`, `raw`, `text` |
| `tags` | No | array/string | — | Additional tags to merge with manifest defaults |

**Example**:
```json
{
  "tool": "ingest_repo",
  "arguments": {
    "project": "billing-domain",
    "repo": "billing-api",
    "mode": "mixed"
  }
}
```

---

### `ingest_file`

Ingest a single file into scoped memory, replacing any existing chunks for that file.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Target scope |
| `repo` | Yes | string | — | Repo name for metadata |
| `path` | Yes | string | — | Absolute or home-relative path to the file |
| `mode` | No | string | `mixed` | Chunking mode |
| `tags` | No | array/string | — | Tags to merge with manifest defaults |

**Example**:
```json
{
  "tool": "ingest_file",
  "arguments": {
    "project": "migration-2026",
    "repo": "product-docs",
    "path": "/Users/me/Downloads/cutover-guide.pdf",
    "tags": ["cutover", "migration"]
  }
}
```

---

### `prune_memories`

Remove duplicate or stale memories from a selected scope.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Scope to prune |
| `repo` | No | string | — | Limit pruning to a specific repo |
| `path_prefix` | No | string | — | Limit pruning to a source path prefix |
| `by` | No | string | `both` | `fingerprint` (dedup), `path` (stale), or `both` |

**Example**:
```json
{
  "tool": "prune_memories",
  "arguments": {
    "project": "billing-domain",
    "repo": "billing-api",
    "by": "both"
  }
}
```

---

### `policy_run`

Run the retention policy for a scope in dry-run or apply mode.

**Policy tiers**:
- **Tier A**: `decision` and `architecture` — always protected
- **Tier B**: `summary` — capped at `summary_keep` per `(repo, topic key)`
- **Tier C**: `code` and `documentation` — pruned by age and duplicate fingerprint

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project` | Yes | string | — | Scope to run policy on |
| `mode` | No | string | `dry-run` | `dry-run` or `apply` |
| `stale_days` | No | integer | 45 | Age threshold for Tier C pruning |
| `summary_keep` | No | integer | 5 | Max summaries per `(repo, topic key)` for Tier B |
| `repo` | No | string | — | Limit policy to a specific repo |
| `path_prefix` | No | string | — | Limit policy to a path prefix |
| `verbose` | No | boolean | false | In dry-run: show per-memory details for each deletion candidate |

**Example**:
```json
{
  "tool": "policy_run",
  "arguments": {
    "project": "migration-2026",
    "mode": "dry-run",
    "verbose": true,
    "stale_days": 30
  }
}
```

---

### `context_plan`

Preview the resolved layered context payloads for a repo. Does not execute searches.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `repo` | Yes | string | — | Repo to resolve context plan for |
| `project` | No | string | — | Override active project |
| `pack` | No | string | `default_3_layer` | Context pack name from manifest |

**Example**:
```json
{
  "tool": "context_plan",
  "arguments": {
    "repo": "billing-api"
  }
}
```

---

## Analytics

### `get_stats`

Return aggregate statistics for a scope without triggering embeddings.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope to inspect |
| `repo` | No | string | — | Filter stats to a specific repo |

**Returns**: `{total_memories, estimated_tokens, oldest_updated_at, newest_updated_at, duplicate_fingerprints, by_category, by_repo, by_source_kind, by_priority}`

**Example**:
```json
{
  "tool": "get_stats",
  "arguments": {
    "project_id": "billing-domain"
  }
}
```

---

### `summarize_scope`

Generate a prose summary of scope contents grouped by category, using the configured LLM.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope to summarize |
| `repo` | No | string | — | Filter to a specific repo |
| `category` | No | string | — | Filter to a specific category |
| `max_tokens` | No | integer | 800 | Approximate max tokens for the generated summary |

**Example**:
```json
{
  "tool": "summarize_scope",
  "arguments": {
    "project_id": "billing-domain",
    "category": "decision",
    "max_tokens": 600
  }
}
```

---

## Diagnostics

### `health_check`

Check connectivity and readiness of all system components.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `skip_slow` | No | boolean | false | Skip model-load checks (embedding + reranker). Use for fast connectivity-only checks. |

**Returns**: Status for `ollama`, `chroma`, `embedding_model`, `reranker` including `ok` boolean and `latency_ms`.

**Example**:
```json
{
  "tool": "health_check",
  "arguments": {
    "skip_slow": false
  }
}
```

---

## Knowledge Graph

### `link_memories`

Create an explicit relationship between two memories.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `source_id` | Yes | string | — | Source memory ID |
| `target_id` | Yes | string | — | Target memory ID |
| `relation` | No | string | `related_to` | `supersedes`, `implements`, `depends_on`, `related_to`, `contradicts`, `refines` |
| `project_id` | No | string | inferred | Scope containing both memories |
| `confidence` | No | number | 1.0 | Confidence score 0.0–1.0 |

**Example**:
```json
{
  "tool": "link_memories",
  "arguments": {
    "source_id": "new-decision-id",
    "target_id": "old-decision-id",
    "relation": "supersedes"
  }
}
```

---

### `get_related`

Get memories related to a given memory through the knowledge graph.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | Yes | string | — | Seed memory ID |
| `project_id` | No | string | inferred | Scope |
| `max_hops` | No | integer | 1 | Traversal depth (1–3) |
| `relation_types` | No | array | — | Filter to specific relation types |
| `response_format` | No | string | `text` | `text` or `json` |

**Example**:
```json
{
  "tool": "get_related",
  "arguments": {
    "memory_id": "abc123",
    "max_hops": 2,
    "relation_types": ["supersedes", "implements"]
  }
}
```

---

### `list_entities`

List known entities extracted from memories in a scope.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope |
| `kind` | No | string | — | Filter by entity kind: `service`, `api`, `module`, `pattern`, `concept`, `tool`, `file` |
| `limit` | No | integer | 50 | Max entities to return |
| `response_format` | No | string | `text` | `text` or `json` |

---

### `search_by_entity`

Find all memories that mention a specific entity.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `entity_name` | Yes | string | — | Entity name to search for |
| `entity_kind` | No | string | — | Entity kind filter |
| `project_id` | No | string | inferred | Scope |
| `response_format` | No | string | `text` | `text` or `json` |

---

### `extract_entities`

Extract and link entities from a specific memory or all memories in scope. Builds/updates the knowledge graph.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope |
| `memory_id` | No | string | — | Specific memory to process. If omitted, processes all memories in scope. |

---

## Version History

### `get_memory_history`

Get the version history of a memory, showing how it changed over time.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `memory_id` | Yes | string | — | Memory ID |
| `project_id` | No | string | inferred | Scope |
| `response_format` | No | string | `text` | `text` or `json` |

---

## Consolidation and Deduplication

### `consolidate_memories`

Find clusters of related memories and optionally consolidate them into summaries.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope |
| `category` | No | string | — | Filter clusters to a specific category |
| `entity` | No | string | — | Find memories related to a specific entity |
| `dry_run` | No | boolean | true | If true, only report what would be consolidated without making changes |

---

### `detect_duplicates`

Find near-duplicate memories using text similarity.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope |
| `threshold` | No | number | 0.92 | Similarity threshold 0.0–1.0 |
| `category` | No | string | — | Filter to a specific category |
| `response_format` | No | string | `text` | `text` or `json` |

**Returns**: Groups of memories with similarity above the threshold.

---

## Migration

### `migrate_to_sqlite`

Migrate existing ChromaDB data to the SQLite metadata store. Safe to run multiple times (idempotent).

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `project_id` | No | string | inferred | Scope to migrate |

Run this once when upgrading an existing installation that predates the SQLite metadata layer.
