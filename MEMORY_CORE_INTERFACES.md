# `memory_core` Package — Interface Summary

## Installation
```bash
pip install -e .   # editable install from repo root
```

## Public API (`from memory_core import ...`)

**`MemoryClient`** — simple 4-method interface to mem0/ChromaDB storage:
```python
from memory_core import MemoryClient, MemoryConfig

client = MemoryClient()  # uses env vars for config
# or:
client = MemoryClient(config=MemoryConfig(
    chroma_path="~/.project-memory",
    ollama_host="http://localhost:11434",
    ollama_model="llama3.2",
    embedding_model="BAAI/bge-large-en-v1.5",
    default_agent_id="my-project",
))

results: list[SearchResult] = client.search("query", limit=5, filters={"project_id": "x"})
entry:   MemoryEntry        = client.store("content", metadata={"category": "decision"})
entries: list[MemoryEntry]  = client.list(filters={"project_id": "x"})
                              client.delete("memory-uuid")
```

**Return types** (no mem0 types leak out):
```python
@dataclass
class SearchResult:
    id: str; content: str; score: float; metadata: dict[str, Any]

@dataclass
class MemoryEntry:
    id: str; content: str; metadata: dict[str, Any]; created_at: datetime | None
```

**`MemoryConfig`** — env var defaults:

| Field | Env var | Default |
|---|---|---|
| `chroma_path` | `PROJECT_MEMORY_ROOT` | `~/.project-memory` |
| `ollama_host` | `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `ollama_model` | `OLLAMA_MODEL` | `llama3.2` |
| `default_agent_id` | `PROJECT_ID` | `project-memory-default` |

---

## Internal modules (also importable, used by `mcp_server.py`)

| Module | Key exports |
|---|---|
| `memory_core.memory_manager` | `MemoryManager` — full hybrid search/store engine |
| `memory_core.memory_types` | `MemoryItem`, `MemoryMetadata`, `StoreMemoryRequest`, `SearchContextRequest`, etc. |
| `memory_core.scoring` | `ScoringEngine`, `RerankerManager` |
| `memory_core.formatting` | `ResultFormatter`, `ExcerptResult` |
| `memory_core.server_config` | `ServerConfig` (dataclass with all server tunables) |
| `memory_core.constants` | `DEFAULT_PROJECT_ID`, `GET_ALL_LIMIT`, `SQLITE_ENABLED`, etc. |
| `memory_core.sqlite_store` | `MetadataStore` (SQLite metadata/knowledge graph backend) |
| `memory_core.manifest` | `build_context_plan`, `guess_repo_root` |
| `memory_core.helpers` | `results_from_payload`, `utc_now`, `_coerce_memory_item`, etc. |
| `memory_core.health` | `run_health_check` |
| `memory_core.summarizer` | `generate_scope_summary` |
| `memory_core.tagging` | `suggest_tags` |
| `memory_core.consolidation` | `run_consolidation`, `ConsolidationEngine` |
| `memory_core.entity_extraction` | `extract_and_link` |

---

## Key design notes
- `MemoryClient` wraps **mem0 directly** — it's independent of `MemoryManager` and the MCP server infrastructure.
- `MemoryManager` is the **complex internal engine** used by the MCP server — hybrid BM25+vector search, SQLite metadata, reranking, etc.
- `mcp_server.py` and `ingest.py` both import from `memory_core.*`; no module-level logic lives at the repo root anymore.
- Tests live in `tests/`; run with `pytest tests/` from the repo root.
