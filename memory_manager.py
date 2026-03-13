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
        UpdateMemoryRequest,
        FindSimilarRequest,
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
    from memory_types import ListMemoriesRequest, DeleteMemoryRequest, StoreMemoryRequest, SearchContextRequest, UpdateMemoryRequest, FindSimilarRequest, MemoryItem  # type: ignore
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
            "priority": getattr(request, "priority", "normal"),
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

        sort_by = getattr(request, "sort_by", "updated_at")
        sort_order = getattr(request, "sort_order", "desc")
        epoch_utc = datetime.fromtimestamp(0, tz=timezone.utc)

        def sort_key(item: MemoryItem) -> Any:
            md = item.metadata
            if sort_by in ("updated_at", "created_at"):
                return parse_datetime(md.updated_at) or epoch_utc
            if sort_by == "category":
                return md.category or ""
            if sort_by == "repo":
                return md.repo or ""
            return parse_datetime(md.updated_at) or epoch_utc

        filtered.sort(key=sort_key, reverse=(sort_order != "asc"))
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

    def update_memory(
        self,
        request: "UpdateMemoryRequest",
    ) -> tuple[bool, str]:
        """Patch an existing memory's body and/or metadata. Returns (found, message)."""
        from memory_types import VALID_PRIORITIES  # type: ignore  # noqa: PLC0415
        item = self.get_memory_item(project_id=request.project_id, memory_id=request.memory_id)
        if item is None:
            return False, f"Memory not found: project={request.project_id} id={request.memory_id}"

        memory = self.get_memory(request.project_id)

        # Build updated body
        new_body = request.body.strip() if request.body and request.body.strip() else item.memory

        # Build patched metadata (merge over existing)
        existing_md = item.metadata.as_dict()
        if request.repo is not None:
            existing_md["repo"] = request.repo
        if request.source_path is not None:
            existing_md["source_path"] = request.source_path
        if request.source_kind is not None:
            existing_md["source_kind"] = request.source_kind
        if request.category is not None:
            existing_md["category"] = request.category
        if request.module is not None:
            existing_md["module"] = request.module
        if request.tags is not None:
            existing_md["tags"] = request.tags
        if request.priority is not None:
            existing_md["priority"] = request.priority
        existing_md["updated_at"] = utc_now()

        # Delete old, re-add with new content and metadata
        memory.delete(request.memory_id)
        result = memory.add(new_body, agent_id=request.project_id, metadata=existing_md, infer=False)
        from helpers import results_from_payload  # type: ignore  # noqa: PLC0415
        stored = results_from_payload(result)
        new_ids = [i.id for i in stored if isinstance(i.id, str)]
        return True, f"Updated memory project={request.project_id} new_id={','.join(new_ids) if new_ids else 'n/a'}"

    def get_stats(
        self,
        project_id: str,
        *,
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregate statistics for a scope without touching embeddings."""
        all_items = self.get_all_items(project_id)

        category_counts: dict[str, int] = {}
        repo_counts: dict[str, int] = {}
        source_kind_counts: dict[str, int] = {}
        priority_counts: dict[str, int] = {"high": 0, "normal": 0, "low": 0}
        oldest: str | None = None
        newest: str | None = None
        total_chars = 0
        fingerprints: dict[str, int] = {}

        for raw_item in all_items:
            item = _coerce_memory_item(raw_item)
            md = item.metadata
            if repo and md.repo != repo:
                continue
            cat = md.category or "general"
            category_counts[cat] = category_counts.get(cat, 0) + 1
            r = md.repo or "unknown"
            repo_counts[r] = repo_counts.get(r, 0) + 1
            sk = md.source_kind or "summary"
            source_kind_counts[sk] = source_kind_counts.get(sk, 0) + 1
            p = md.priority if md.priority in {"high", "normal", "low"} else "normal"
            priority_counts[p] = priority_counts.get(p, 0) + 1
            total_chars += len(item.memory)
            fp = md.fingerprint
            if fp:
                fingerprints[fp] = fingerprints.get(fp, 0) + 1
            ts = md.updated_at
            if ts:
                if oldest is None or ts < oldest:
                    oldest = ts
                if newest is None or ts > newest:
                    newest = ts

        total = sum(category_counts.values())
        duplicate_fingerprints = sum(1 for count in fingerprints.values() if count > 1)
        estimated_tokens = int(total_chars / 4)

        return {
            "project_id": project_id,
            "repo_filter": repo,
            "total_memories": total,
            "estimated_tokens": estimated_tokens,
            "oldest_updated_at": oldest,
            "newest_updated_at": newest,
            "duplicate_fingerprints": duplicate_fingerprints,
            "by_category": category_counts,
            "by_repo": repo_counts,
            "by_source_kind": source_kind_counts,
            "by_priority": priority_counts,
        }

    def find_similar(
        self,
        request: "FindSimilarRequest",
    ) -> list[dict[str, Any]]:
        """Find memories similar to a given text or an existing memory ID."""
        query_text: str
        if request.memory_id:
            item = self.get_memory_item(project_id=request.project_id, memory_id=request.memory_id)
            if item is None:
                return []
            query_text = item.memory
        elif request.text:
            query_text = request.text
        else:
            return []

        memory = self.get_memory(request.project_id)
        raw_results = results_from_payload(
            memory.search(query=query_text, agent_id=request.project_id, limit=request.limit + 5)
        )
        results: list[dict[str, Any]] = []
        for raw in raw_results:
            item = _coerce_memory_item(raw)
            # Skip the seed item itself
            if request.memory_id and item.id == request.memory_id:
                continue
            score = item.extra.get("score", 0.0) if hasattr(item, "extra") else 0.0
            results.append({
                "id": item.id,
                "score": score,
                "memory": item.memory,
                "metadata": item.metadata.as_dict(),
            })
            if len(results) >= request.limit:
                break
        return results

    def bulk_store(
        self,
        memories: list[dict[str, Any]],
        *,
        project_id: str,
        pre_fetched_items: list | None = None,
    ) -> list[dict[str, Any]]:
        """Store multiple memories in one call. Returns per-item results."""
        from memory_types import StoreMemoryRequest, VALID_PRIORITIES  # type: ignore  # noqa: PLC0415
        items = pre_fetched_items if pre_fetched_items is not None else self.get_all_items(project_id)
        results: list[dict[str, Any]] = []
        for mem in memories:
            try:
                source_kind = str(mem.get("source_kind") or "summary")
                category = str(mem.get("category") or source_kind)
                raw_priority = mem.get("priority")
                priority = raw_priority if isinstance(raw_priority, str) and raw_priority in VALID_PRIORITIES else "normal"
                request = StoreMemoryRequest(
                    project_id=project_id,
                    content=str(mem.get("content") or mem.get("body") or "").strip(),
                    repo=mem.get("repo") or None,
                    source_path=mem.get("source_path") or None,
                    source_kind=source_kind,
                    category=category,
                    module=mem.get("module") or None,
                    tags=[t for t in (mem.get("tags") or []) if isinstance(t, str)],
                    upsert_key=mem.get("upsert_key") or None,
                    fingerprint=mem.get("fingerprint") or None,
                    priority=priority,
                )
                if not request.content:
                    results.append({"ok": False, "error": "empty content", "ids": []})
                    continue
                deleted_count, new_ids = self.store_memory(request, pre_fetched_items=items)
                results.append({"ok": True, "deleted_existing": deleted_count, "ids": new_ids})
            except Exception as exc:
                results.append({"ok": False, "error": str(exc), "ids": []})
        return results

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
        # Parse date range filters once
        after_date = parse_datetime(getattr(request, "after_date", None))
        before_date = parse_datetime(getattr(request, "before_date", None))

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
                # Date range filtering
                if after_date or before_date:
                    updated = parse_datetime(item.metadata.updated_at)
                    if after_date and (updated is None or updated < after_date):
                        continue
                    if before_date and (updated is None or updated > before_date):
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
