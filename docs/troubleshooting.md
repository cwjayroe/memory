# Troubleshooting

## Health Check

The fastest way to diagnose system issues is `health_check`. Run it via MCP:

```json
{"tool": "health_check", "arguments": {"skip_slow": false}}
```

Or via the examples script:
```bash
python examples.py
```

`skip_slow=false` runs all checks including model-load verification (takes ~10-30s on first run).

### What Each Check Tests

| Check | What It Does | Failure Means |
|-------|-------------|---------------|
| `ollama_ok` | HTTP GET to `OLLAMA_BASE_URL/api/tags` | Ollama is not running or unreachable |
| `ollama_latency_ms` | Round-trip time to Ollama | High values (>500ms) may cause timeouts on long operations |
| `chroma_ok` | Read + write test on a temporary Chroma collection | Storage path issue, permission error, or ChromaDB version mismatch |
| `embedding_ok` | Loads `multi-qa-MiniLM-L6-cos-v1` and runs a test encode | Model not downloaded, OOM, or missing `sentence-transformers` |
| `reranker_ok` | Loads reranker model and runs a test score | Model not downloaded, OOM, or missing `sentence-transformers` |

---

## Common Issues

### No Search Results Returned

**Symptoms**: `search_context` returns empty results or only org_practice entries.

**Diagnoses**:

1. **Wrong scope**: Check the `scope_source` field in the response header.
   - `inferred` → query tokens didn't match your project tags well; add more tags to your project in `projects.yaml`
   - `fallback` → no project matched at all; verify `PROJECT_ID` env or add explicit `project_id` to the call

2. **Empty scope**: The project has no stored memories.
   ```bash
   python ingest.py list --project your-project --limit 5
   ```
   If empty, ingest content first.

3. **Scope name mismatch**: `project_id` in the call doesn't match any key in `projects.yaml`.
   ```bash
   python ingest.py list --project exact-project-id
   ```

4. **Token budget too small**: All candidates exceeded the budget.
   - Retry with `token_budget=4000` and `limit=3` to confirm results exist.

---

### Results Seem Irrelevant

**Symptoms**: Results are returned but don't match the query intent.

**Diagnoses**:

1. **Use `response_format="json"` and `debug=true`** to inspect per-result scores:
   - Low `vector_score` + low `reranker_score` → semantic mismatch; consider whether the right content is stored
   - High `bm25_score` only → BM25 matching on incidental keywords; try a more specific query

2. **Check category filter**: If searching for decisions, add `categories=["decision"]` to exclude noisy code/doc results.

3. **Reranker not running**: If `reranker_ok=false` in health check, results use hybrid-only scoring which is less precise for technical queries.

---

### Reranker Unavailable

**Symptoms**: `health_check` returns `reranker_ok: false`. Searches fall back to `hybrid_weighted`.

**Fixes**:

1. **Model not downloaded**: The model downloads automatically on first use. Trigger a download by running:
   ```bash
   python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"
   ```

2. **Wrong model name**: Check `PROJECT_MEMORY_RERANKER_MODEL`. Default is `BAAI/bge-reranker-v2-m3`.

3. **OOM**: The reranker requires ~500MB RAM. Reduce `PROJECT_MEMORY_DEFAULT_RERANK_TOP_N` to lower memory pressure, or switch to `PROJECT_MEMORY_RANKING_MODE=hybrid_weighted` permanently.

4. **Missing dependency**: Ensure `sentence-transformers` and `torch` are installed:
   ```bash
   pip install sentence-transformers torch
   ```

---

### Ollama Connection Refused

**Symptoms**: `health_check` returns `ollama_ok: false`. Store/search operations fail with connection errors.

**Fixes**:

1. Start Ollama:
   ```bash
   ollama serve
   ```

2. Verify the URL: default is `http://localhost:11434`. Override with `OLLAMA_BASE_URL` if Ollama runs elsewhere.

3. Pull the required model:
   ```bash
   ollama pull llama3.2
   ```
   Override the model name with `OLLAMA_MODEL`.

4. Verify connectivity:
   ```bash
   curl http://localhost:11434/api/tags
   ```

---

### ChromaDB Errors

**Symptoms**: `chroma_ok: false` in health check, or errors like `Collection not found` or `Permission denied`.

**Fixes**:

1. **Storage path**: Check `PROJECT_MEMORY_ROOT`. Default is `~/.project-memory`. Ensure it exists and is writable:
   ```bash
   mkdir -p ~/.project-memory
   ls -la ~/.project-memory
   ```

2. **Disk space**: ChromaDB writes embeddings to disk. Run `df -h ~/.project-memory`.

3. **Version mismatch**: ChromaDB collections created with an older version may be incompatible. Back up and clear:
   ```bash
   python ingest.py export --project your-project --output ./backup.ndjson
   rm -rf ~/.project-memory/your-project/
   python ingest.py import --project your-project --file ./backup.ndjson
   ```

4. **Concurrent access**: Multiple server instances writing to the same Chroma collection can corrupt state. Ensure only one server instance runs per `PROJECT_MEMORY_ROOT`.

---

### Duplicate Results

**Symptoms**: Search returns the same or near-identical content multiple times.

**Fixes**:

1. Run pruning:
   ```bash
   python ingest.py prune --project your-project --by fingerprint
   ```

2. Check for near-duplicates via MCP:
   ```json
   {"tool": "detect_duplicates", "arguments": {"project_id": "your-project", "threshold": 0.92}}
   ```

3. If duplicates exist across different `source_path` values (e.g., same file ingested with different paths), they won't be caught by fingerprint pruning alone. Use `detect_duplicates` to identify and `delete_memory` to remove the extras.

---

### PDF Has No Extractable Text

**Symptoms**: Ingested PDF returns placeholder chunks with no searchable content.

**Cause**: The PDF is image-based (scanned) and has no embedded text layer.

**Fix**: Use an OCR tool to add a text layer before ingesting:
- `ocrmypdf input.pdf output.pdf` (if `ocrmypdf` is installed)
- Adobe Acrobat OCR
- Google Drive (open PDF → auto-OCR → download as PDF)

Then re-ingest the OCR'd file.

---

### Memory Body Truncated in Text Mode

**Symptoms**: Search result excerpt cuts off at ~420 characters; full content not visible.

**Fix**: Use `get_memory` for the exact stored body:

```json
{"tool": "get_memory", "arguments": {"memory_id": "abc123"}}
```

Or use `response_format="json"` with `include_full_text=true` in `search_context` to include full bodies in the search response.

---

### Ingest Slow for Large Repos

**Symptoms**: `repo` command takes many minutes for large repositories.

**Causes and mitigations**:

1. **Embedding bottleneck**: Each chunk requires an Ollama embedding call. For large repos, embed in batches or run during off-hours.

2. **Too many files included**: Review `include` globs in the manifest. Exclude generated files, migrations, build outputs:
   ```yaml
   exclude:
     - '**/migrations/**'
     - '**/build/**'
     - '**/dist/**'
     - '**/*.min.js'
   ```

3. **Dedup avoiding re-work**: Re-ingest after a small edit? Most chunks will fingerprint-match and be skipped quickly. Only changed files incur embedding cost.

4. **Use `watch` for incremental updates**: Instead of re-running `repo` after every edit, use `watch` to auto-ingest only changed files.

---

## Debugging Techniques

### Inspect Scope Resolution

Add `response_format="json"` to any `search_context` call. The response JSON includes:
- `scope_source`: `explicit` | `inferred` | `fallback` | `retry`
- `resolved_projects`: list of project IDs that were searched

### Score Breakdown

Add `debug=true` to `search_context`. Each result in the JSON response includes:
- `vector_score`, `bm25_score`, `metadata_score`, `reranker_score`, `final_score`

Useful for understanding why a result ranked where it did.

### Attach Debugger

Start the server with debugpy for IDE-level debugging:

```bash
python -m debugpy --listen 5678 --wait-for-client ./mcp_server.py
```

Attach your IDE debugger to `127.0.0.1:5678`. The server waits for the debugger before starting.

### Access Log Analytics

The `access_log` SQLite table records every search result delivered, with query text, memory ID, rank position, and timestamp. Query it directly:

```bash
sqlite3 ~/.project-memory/memory.db \
  "SELECT query, memory_id, rank_position, queried_at
   FROM access_log
   ORDER BY queried_at DESC
   LIMIT 20;"
```

Useful for understanding which memories are being retrieved most often and in what queries.

### Scope Statistics

Use `get_stats` to audit a scope without triggering embeddings:

```json
{"tool": "get_stats", "arguments": {"project_id": "billing-domain"}}
```

Returns: total count, breakdown by category/repo/source_kind/priority, oldest/newest timestamps, estimated token coverage, duplicate fingerprint count.

### Run Examples Script

`examples.py` spawns a local MCP server and runs a set of sanity-check operations (list tools, search, store, delete). Good for verifying a fresh install:

```bash
python examples.py
```
