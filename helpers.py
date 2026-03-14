from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

from memory_types import SearchContextRequest, MemoryItem
from constants import (
    DEFAULT_PROJECT_ID,
    MEMORY_ROOT,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    GET_ALL_LIMIT
)
from server_config import ServerConfig

if TYPE_CHECKING:
    from mem0 import Memory


def _normalize_project_ids(value: Any, max_projects: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            if isinstance(item, str):
                raw_items.append(item.strip())
    else:
        return []

    return dedupe_keep_order(raw_items)[:max_projects]


def _resolve_org_practice_projects(
    max_projects_per_query: int, manifest_path: str
) -> list[str]:
    try:
        from .manifest import load_project_index_with_cache, resolve_org_practice_projects
    except ImportError:  # pragma: no cover - direct script/import fallback
        from manifest import load_project_index_with_cache, resolve_org_practice_projects  # type: ignore

    index = load_project_index_with_cache(
        manifest_path=manifest_path,
        default_project_id=DEFAULT_PROJECT_ID,
        memory_root=MEMORY_ROOT,
    )
    return resolve_org_practice_projects(index, max_projects_per_query)


def _resolve_search_scope(
    request: SearchContextRequest,
    config: ServerConfig,
) -> tuple[list[str], str, list[tuple[str, float]]]:
    try:
        from .manifest import infer_projects_from_query, load_project_index_with_cache
    except ImportError:  # pragma: no cover - direct script/import fallback
        from manifest import infer_projects_from_query, load_project_index_with_cache  # type: ignore

    if request.project_ids:
        project_ids = _normalize_project_ids(request.project_ids, config.max_projects_per_query)
        return project_ids, "explicit", []

    if request.project_id:
        return [request.project_id], "explicit", []

    index = load_project_index_with_cache(
        manifest_path=config.manifest_path,
        default_project_id=DEFAULT_PROJECT_ID,
        memory_root=MEMORY_ROOT,
    )

    inferred = infer_projects_from_query(
        query=request.query,
        repo_hint=request.repo,
        max_projects=config.inference_max_projects,
        index=index,
    )
    if inferred:
        return [project_id for project_id, _ in inferred], "inferred", inferred

    return [DEFAULT_PROJECT_ID], "inferred-empty", []


def _is_transient_memory_init_error(exc: Exception) -> bool:
    message = str(exc)
    transient_markers = [
        "RustBindingsAPI",
        "no attribute 'bindings'",
        "Could not connect to tenant",
    ]
    return any(marker in message for marker in transient_markers)


def _coerce_memory_item(memory_item: MemoryItem | dict[str, Any]) -> MemoryItem:
    if isinstance(memory_item, MemoryItem):
        return memory_item
    return MemoryItem.from_dict(memory_item)


def _matches_filters(
    memory_item: MemoryItem | dict[str, Any],
    *,
    repo: str | None = None,
    path_prefix: str | None = None,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
) -> bool:
    item = _coerce_memory_item(memory_item)
    metadata = item.metadata

    if repo and metadata.repo != repo:
        return False

    if path_prefix:
        source_path = metadata.source_path
        if not source_path or not source_path.startswith(path_prefix):
            return False

    if categories:
        if metadata.category not in categories:
            return False

    if tags:
        if not set(tags).intersection(metadata.tags):
            return False

    return True


def _find_ids(
    memories: list[MemoryItem],
    *,
    upsert_key: str | None = None,
    fingerprint: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for memory_item in memories:
        metadata = memory_item.metadata
        memory_id = memory_item.id
        if not isinstance(memory_id, str):
            continue
        if upsert_key and metadata.upsert_key == upsert_key:
            ids.append(memory_id)
        elif fingerprint and metadata.fingerprint == fingerprint:
            ids.append(memory_id)
    return ids


def _build_search_cache_key(
    request: SearchContextRequest, project_ids: list[str]
) -> str:
    normalized = {
        "query": request.query,
        "project_ids": project_ids,
        "repo": request.repo,
        "path_prefix": request.path_prefix,
        "tags": sorted(request.tags),
        "categories": sorted(request.categories),
        "limit": request.limit,
        "ranking_mode": request.ranking_mode,
        "token_budget": request.token_budget,
        "candidate_pool": request.candidate_pool,
        "rerank_top_n": request.rerank_top_n,
        "response_format": request.response_format,
        "include_full_text": request.include_full_text,
        "excerpt_chars": request.excerpt_chars,
    }
    key_source = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(key_source.encode("utf-8")).hexdigest()


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()]
    if isinstance(value, list):
        tags = []
        for item in value:
            if isinstance(item, str) and item.strip():
                tags.append(item.strip())
        return tags
    return []


def normalize_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
        return items
    return []


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_mem0_config(project_id: str) -> dict[str, Any]:
    return {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": OLLAMA_MODEL,
                "ollama_base_url": OLLAMA_BASE_URL,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {"model": "BAAI/bge-large-en-v1.5"},
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": f"project-memory-{project_id}",
                "path": os.path.join(MEMORY_ROOT, project_id, "chroma"),
            },
        },
    }


def results_from_payload(payload: Any) -> list[MemoryItem]:
    if isinstance(payload, dict):
        data = payload.get("results")
        if isinstance(data, list):
            return [MemoryItem.from_dict(item) for item in data if isinstance(item, dict)]
    return []


def get_all_items(memory: Memory, project_id: str, *, limit: int = GET_ALL_LIMIT) -> list[MemoryItem]:
    return results_from_payload(memory.get_all(agent_id=project_id, limit=limit))
