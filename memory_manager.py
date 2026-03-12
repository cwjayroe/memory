from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from mem0 import Memory

if __package__ in {None, ""}:
    current_dir = Path(__file__).resolve().parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
try:
    from .scoring import (
        ScoringEngine,
    )
    from .constants import (
        DEFAULT_PROJECT_ID,
        GET_ALL_LIMIT,
    )
    from .server_config import ServerConfig
    from .memory_types import (
        ListMemoriesRequest,
        DeleteMemoryRequest,
        StoreMemoryRequest,
        SearchContextRequest,
        MemoryItem,
    )
    from .helpers import (
        _is_transient_memory_init_error,
        _find_ids,
        _coerce_memory_item,
        _matches_filters,
        get_all_items,
        parse_datetime,
        utc_now,
        results_from_payload,
        build_mem0_config,
    )
except ImportError:  # pragma: no cover - direct script/import fallback
    from scoring import (  # type: ignore
        ScoringEngine,
    )
    from constants import (  # type: ignore
        DEFAULT_PROJECT_ID,
        GET_ALL_LIMIT,
    )
    from memory_types import ListMemoriesRequest, DeleteMemoryRequest, StoreMemoryRequest, SearchContextRequest, MemoryItem  # type: ignore
    from server_config import ServerConfig  # type: ignore
    from helpers import _is_transient_memory_init_error, _find_ids, _coerce_memory_item, _matches_filters, get_all_items, parse_datetime, utc_now, results_from_payload, build_mem0_config  # type: ignore


class MemoryManager:
    """Manages Memory instances, caching, and CRUD operations for project memories."""

    def __init__(
        self,
        *,
        config: ServerConfig | None = None,
        scoring_engine: ScoringEngine | None = None,
        logger: logging.Logger,
        default_project_id: str = DEFAULT_PROJECT_ID,
        get_all_limit: int = GET_ALL_LIMIT,
    ):
        self._config = config
        self._scoring_engine = scoring_engine
        self._logger = logger
        self._default_project_id = default_project_id
        self._get_all_limit = get_all_limit
        self._memory_cache: dict[str, Memory] = {}
        self._memory_cache_lock = threading.Lock()
        self._search_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

    # -- Memory instance lifecycle ------------------------------------------

    def _get_memory_uncached(self, project_id: str) -> Memory:
        with self._memory_cache_lock:
            existing = self._memory_cache.get(project_id)
            if existing is not None:
                return existing
            memory = Memory.from_config(build_mem0_config(project_id))
            self._memory_cache[project_id] = memory
            return memory

    def _clear_cache_entry(self, project_id: str) -> None:
        with self._memory_cache_lock:
            self._memory_cache.pop(project_id, None)

    def get_memory(
        self,
        project_id: str,
        *,
        retries: int = 2,
        backoff_seconds: float = 0.2,
    ) -> Memory:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self._get_memory_uncached(project_id)
            except (
                Exception
            ) as exc:  # pragma: no cover - exercised in resilience tests via monkeypatch
                last_exc = exc
                if attempt >= retries or not _is_transient_memory_init_error(exc):
                    raise
                self._logger.warning(
                    "Transient memory init error for project=%s (attempt=%s/%s). Retrying.",
                    project_id,
                    attempt + 1,
                    retries + 1,
                    exc_info=True,
                )
                self._clear_cache_entry(project_id)
                time.sleep(backoff_seconds * (attempt + 1))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Unable to initialize memory for project={project_id}")

    def get_all_items(self, project_id: str) -> list[MemoryItem]:
        memory = self.get_memory(project_id)
        return get_all_items(memory, project_id, limit=self._get_all_limit)

    # -- CRUD operations ----------------------------------------------------

    def store_memory(
        self,
        request: StoreMemoryRequest,
        *,
        pre_fetched_items: list | None = None,
    ) -> tuple[int, list[str]]:
        """Store a memory with dedup. Returns (deleted_existing_count, new_memory_ids).

        Pass ``pre_fetched_items`` to skip the internal get_all_items() call (batch
        optimization: fetch once per file, reuse across all chunks).
        """
        memory = self.get_memory(request.project_id)

        fingerprint = request.fingerprint
        if not fingerprint:
            fingerprint_input = "||".join(
                [
                    request.project_id,
                    str(request.repo or ""),
                    str(request.source_path or ""),
                    request.source_kind,
                    request.content,
                ]
            )
            fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()

        metadata: dict[str, Any] = {
            "project_id": request.project_id,
            "category": request.category,
            "source_kind": request.source_kind,
            "updated_at": utc_now(),
            "fingerprint": fingerprint,
        }
        if request.tags:
            metadata["tags"] = request.tags
        if request.repo:
            metadata["repo"] = request.repo
        if request.source_path:
            metadata["source_path"] = request.source_path
        if request.module:
            metadata["module"] = request.module
        if request.upsert_key:
            metadata["upsert_key"] = request.upsert_key

        all_memories = (
            pre_fetched_items
            if pre_fetched_items is not None
            else get_all_items(memory, request.project_id, limit=self._get_all_limit)
        )
        delete_ids = _find_ids(
            all_memories,
            upsert_key=request.upsert_key,
            fingerprint=None if request.upsert_key else fingerprint,
        )
        for mid in delete_ids:
            memory.delete(mid)

        result = memory.add(
            request.content, agent_id=request.project_id, metadata=metadata, infer=False
        )
        stored = results_from_payload(result)
        stored_ids = [item.id for item in stored if isinstance(item.id, str)]
        return len(delete_ids), stored_ids

    def list_memories(
        self,
        request: ListMemoriesRequest,
    ) -> tuple[list[MemoryItem], int]:
        """Filter, sort, and paginate memories. Returns (page, total_matches)."""
        memory = self.get_memory(request.project_id)
        all_memories = get_all_items(
            memory, request.project_id, limit=self._get_all_limit
        )

        filtered: list[MemoryItem] = []
        for raw_item in all_memories:
            item = _coerce_memory_item(raw_item)
            md = item.metadata
            if request.repo and md.repo != request.repo:
                continue
            if request.category and md.category != request.category:
                continue
            if request.path_prefix:
                sp = md.source_path
                if not sp or not sp.startswith(request.path_prefix):
                    continue
            if request.tag:
                if request.tag not in md.tags:
                    continue
            filtered.append(item)

        epoch_utc = datetime.fromtimestamp(0, tz=timezone.utc)
        filtered.sort(
            key=lambda item: parse_datetime(item.metadata.updated_at) or epoch_utc,
            reverse=True,
        )
        page = filtered[request.offset : request.offset + request.limit]
        return page, len(filtered)

    def get_memory_item(
        self,
        *,
        project_id: str,
        memory_id: str,
    ) -> MemoryItem | None:
        if not memory_id:
            return None

        memory = self.get_memory(project_id)
        all_memories = get_all_items(
            memory, project_id, limit=self._get_all_limit
        )
        for raw_item in all_memories:
            item = _coerce_memory_item(raw_item)
            if item.id == memory_id:
                return item
        return None

    def delete_memory(
        self,
        request: DeleteMemoryRequest,
    ) -> tuple[str, int]:
        """Delete by ID or upsert_key. Returns (description, deleted_count)."""
        memory = self.get_memory(request.project_id)

        if request.memory_id:
            memory.delete(request.memory_id)
            return (
                f"Deleted memory_id={request.memory_id} from project={request.project_id}.",
                1,
            )

        if request.upsert_key:
            all_memories = get_all_items(
                memory, request.project_id, limit=self._get_all_limit
            )
            ids = _find_ids(all_memories, upsert_key=request.upsert_key)
            for item_id in ids:
                memory.delete(item_id)
            return (
                f"Deleted {len(ids)} memories with upsert_key={request.upsert_key} from project={request.project_id}.",
                len(ids),
            )

        return "Provide memory_id or upsert_key.", 0

    # -- Search cache -------------------------------------------------------

    def search_cache_get(self, cache_key: str) -> str | None:
        cached = self._search_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, payload = cached
        if time.time() >= expires_at:
            self._search_cache.pop(cache_key, None)
            return None
        self._search_cache.move_to_end(cache_key)
        return payload

    def search_cache_set(self, cache_key: str, payload: str) -> None:
        expires_at = time.time() + self._config.cache_ttl_seconds
        self._search_cache[cache_key] = (expires_at, payload)
        self._search_cache.move_to_end(cache_key)
        while len(self._search_cache) > self._config.cache_max_entries:
            self._search_cache.popitem(last=False)

    # -- Search pipeline ----------------------------------------------------

    def _search_project_sync(
        self, project_id: str, query: str, candidate_limit: int
    ) -> list[MemoryItem]:
        memory = self.get_memory(project_id)
        return results_from_payload(
            memory.search(query=query, agent_id=project_id, limit=candidate_limit)
        )

    async def _search_project_candidates(
        self, project_id: str, query: str, candidate_limit: int
    ) -> list[MemoryItem]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._search_project_sync, project_id, query, candidate_limit
                ),
                timeout=self._config.project_timeout_seconds,
            )
        except Exception:
            return []

    async def _collect_project_searches(
        self, project_ids: list[str], query: str, candidate_limit: int
    ) -> dict[str, list[MemoryItem]]:
        tasks = {}
        for project_id in project_ids:
            tasks[project_id] = asyncio.create_task(
                self._search_project_candidates(project_id, query, candidate_limit)
            )

        done, pending = await asyncio.wait(
            tasks.values(), timeout=self._config.global_timeout_seconds
        )
        for task in pending:
            task.cancel()

        results_by_project: dict[str, list[MemoryItem]] = {}
        for project_id, task in tasks.items():
            if task in done:
                try:
                    results_by_project[project_id] = task.result()
                except Exception:
                    results_by_project[project_id] = []
            else:
                results_by_project[project_id] = []
        return results_by_project

    def _warm_memory_handles(self, project_ids: list[str]) -> None:
        for project_id in project_ids:
            try:
                self.get_memory(project_id)
            except Exception:
                self._logger.warning(
                    "Failed to warm memory handle for project=%s",
                    project_id,
                    exc_info=True,
                )

    async def search(
        self,
        request: SearchContextRequest,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Run full search pipeline across projects. Returns (packed_results, rerank_used)."""
        if self._scoring_engine is None or self._config is None:
            raise RuntimeError(
                "search() requires scoring_engine and config. Pass them to MemoryManager.__init__."
            )
        tags = request.tags or []
        categories = request.categories or []
        ranking_mode = request.ranking_mode or self._config.default_ranking_mode
        rerank_top_n = request.rerank_top_n or self._config.default_rerank_top_n
        token_budget = request.token_budget or self._config.default_token_budget
        candidate_pool = request.candidate_pool or self._config.max_candidate_pool

        self._warm_memory_handles(request.project_ids)
        project_results = await self._collect_project_searches(
            request.project_ids, request.query, candidate_pool
        )
        merged_candidates: list[dict[str, Any]] = []
        for search_project_id in request.project_ids:
            for raw_item in project_results.get(search_project_id, []):
                item = _coerce_memory_item(raw_item)
                if not _matches_filters(
                    item,
                    repo=request.repo,
                    path_prefix=request.path_prefix,
                    tags=tags,
                    categories=categories,
                ):
                    continue
                merged_item = item.as_dict()
                metadata = item.metadata.as_dict()
                if not item.metadata.project_id:
                    metadata["project_id"] = search_project_id
                merged_item["metadata"] = metadata
                merged_item["_project_id"] = search_project_id
                merged_candidates.append(merged_item)

        deduped_candidates = self._scoring_engine.dedupe_candidates(merged_candidates)
        if not deduped_candidates:
            return [], False

        scored_candidates = self._scoring_engine.score_candidates(
            request.query,
            deduped_candidates,
            repo=request.repo,
            path_prefix=request.path_prefix,
            tags=request.tags,
            categories=request.categories,
            ranking_mode=ranking_mode,
            rerank_top_n=rerank_top_n,
        )

        rerank_used = False
        if ranking_mode == "hybrid_weighted_rerank":
            rerank_used = await asyncio.to_thread(
                self._scoring_engine.reranker.apply,
                request.query,
                scored_candidates,
                rerank_top_n,
            )
        finalized = self._scoring_engine.finalize_scores(scored_candidates)
        packed = self._scoring_engine.pack_candidates(
            finalized, limit=request.limit, token_budget=token_budget
        )
        return packed, rerank_used
