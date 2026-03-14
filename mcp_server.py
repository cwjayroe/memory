"""Scoped, repo-aware memory server for MCP clients."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from memory_types import (
    DeleteMemoryRequest,
    FindSimilarRequest,
    GetMemoryRequest,
    ListMemoriesRequest,
    SearchContextParsePolicy,
    SearchContextRequest,
    StoreMemoryRequest,
    UpdateMemoryRequest,
)
from formatting import ResultFormatter
from scoring import RerankerManager, ScoringEngine
from constants import DEFAULT_PROJECT_ID, GET_ALL_LIMIT
from server_config import ServerConfig
from memory_manager import MemoryManager
from helpers import (
    _resolve_search_scope,
    _build_search_cache_key,
    _resolve_org_practice_projects,
    dedupe_keep_order,
    normalize_strings,
    normalize_tags,
    safe_dict as _safe_dict,
)
from ingest import ingest_file, collect_files, build_policy_actions
from manifest import (
    build_context_plan,
    resolve_repo_config,
    read_manifest,
    write_manifest,
    validate_project_id,
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    guess_repo_root,
)
from rate_limiter import RateLimiter
from access_control import AccessController
from metrics import METRICS, OperationTimer, new_correlation_id, configure_structured_logging
from cache_backend import create_cache_backend

LOGGER = logging.getLogger(__name__)
config = ServerConfig.from_env()

# Structured logging for production deployments
if config.structured_logging:
    configure_structured_logging()

app = Server("memory")
scoring_engine = ScoringEngine(
    reranker=RerankerManager(config.reranker_model_name),
)

# Enterprise: pluggable cache backend
cache_backend = create_cache_backend(
    backend=config.cache_backend,
    max_entries=config.cache_max_entries,
    default_ttl=config.cache_ttl_seconds,
    redis_url=config.redis_url,
    redis_key_prefix=config.redis_key_prefix,
)

mem_manager = MemoryManager(
    config=config,
    scoring_engine=scoring_engine,
    logger=LOGGER,
    cache_backend=cache_backend,
)

# Enterprise: rate limiter and access control
rate_limiter = RateLimiter(enabled=config.rate_limit_enabled)
access_controller = AccessController(enabled=config.access_control_enabled)
access_controller.load_from_env()


SEARCH_PARSE_POLICY = SearchContextParsePolicy(
    max_projects_per_query=config.max_projects_per_query,
    default_limit=8,
    max_limit=20,
    default_ranking_mode=config.default_ranking_mode,
    allowed_ranking_modes=frozenset({"hybrid_weighted_rerank", "hybrid_weighted"}),
    default_token_budget=config.default_token_budget,
    min_token_budget=config.min_token_budget,
    max_token_budget=config.max_token_budget,
    default_rerank_top_n=config.default_rerank_top_n,
    max_candidate_pool=config.max_candidate_pool,
)

# ---------------------------------------------------------------------------
# MCP handlers (thin wrappers: parse request -> delegate to _manager -> format)
# ---------------------------------------------------------------------------


async def _handle_search_context(arguments: dict[str, Any]) -> list[TextContent]:
    formatter = ResultFormatter()
    request = SearchContextRequest.from_arguments(arguments, policy=SEARCH_PARSE_POLICY)
    if not request.query:
        return [TextContent(type="text", text="Query cannot be empty.")]

    # Handle search_all_scopes: enumerate all manifest projects
    if request.search_all_scopes:
        try:
            from manifest import read_manifest as _read_manifest
            _manifest = _read_manifest(Path(config.manifest_path))
            _all_projects = list((_manifest.get("projects") or {}).keys())
        except Exception:
            _all_projects = []
        if not _all_projects:
            _all_projects = [DEFAULT_PROJECT_ID]
        max_scopes = config.max_projects_per_query * 3
        project_ids = _all_projects[:max_scopes]
        scope_source = "all-scopes"
        inference_candidates = []
    else:
        project_ids, scope_source, inference_candidates = _resolve_search_scope(
            request,
            config
        )
    request = replace(request, project_ids=project_ids)
    cache_key = _build_search_cache_key(request, project_ids)
    if not request.debug:
        cached_payload = mem_manager.search_cache_get(cache_key)
        if cached_payload is not None:
            return [TextContent(type="text", text=cached_payload)]

    packed, rerank_used = await mem_manager.search(
        request=request
    )

    if not packed and scope_source in {"inferred", "inferred-empty"}:
        org_practice_projects = _resolve_org_practice_projects(config.max_projects_per_query, config.manifest_path)
        default_project_ids = [DEFAULT_PROJECT_ID] + org_practice_projects
        retry_project_ids = dedupe_keep_order(default_project_ids)[: config.max_projects_per_query]

        if retry_project_ids and retry_project_ids != project_ids:
            request = replace(request, project_ids=retry_project_ids)
            retry_packed, retry_rerank_used = await mem_manager.search(
                request=request
            )
            if retry_packed:
                packed = retry_packed
                rerank_used = retry_rerank_used
                project_ids = retry_project_ids
                scope_source = "fallback-retry"

    if not packed:
        return [
            TextContent(
                type="text",
                text=formatter.format_search_no_results(
                    request=request,
                    project_ids=project_ids,
                    scope_source=scope_source,
                ),
            )
        ]

    payload = formatter.format_search_payload(
        packed=packed,
        request=request,
        project_ids=project_ids,
        scope_source=scope_source,
        rerank_used=rerank_used,
        inference_candidates=inference_candidates,
        reranker_load_error=scoring_engine.reranker.load_error,
    )
    if not request.debug:
        mem_manager.search_cache_set(cache_key, payload)
    return [TextContent(type="text", text=payload)]


async def _handle_store_memory(arguments: dict[str, Any]) -> list[TextContent]:
    request = StoreMemoryRequest.from_arguments(
        arguments, default_project_id=DEFAULT_PROJECT_ID
    )
    if not request.content:
        return [TextContent(type="text", text="Cannot store empty content.")]

    deleted_count, new_ids = mem_manager.store_memory(
        request=request
    )
    text = (
        f"Stored memory in project={request.project_id}. "
        f"deleted_existing={deleted_count} new_ids={','.join(new_ids) if new_ids else 'n/a'} "
        f"priority={request.priority}"
    )

    # Optional tag suggestion
    if bool(arguments.get("suggest_tags", False)):
        from tagging import suggest_tags
        suggestions = suggest_tags(request.content, max_suggestions=5)
        if suggestions:
            text += f"\nsuggested_tags={','.join(suggestions)}"

    return [TextContent(type="text", text=text)]


async def _handle_list_memories(arguments: dict[str, Any]) -> list[TextContent]:
    formatter = ResultFormatter()
    request = ListMemoriesRequest.from_arguments(
        arguments,
        default_project_id=DEFAULT_PROJECT_ID,
        default_limit=20,
        max_limit=100,
    )

    page, total_matches = mem_manager.list_memories(request=request)

    if not page:
        return [
            TextContent(
                type="text",
                text=formatter.format_list_no_results(
                    request=request,
                    total_matches=total_matches,
                ),
            )
        ]

    return [
        TextContent(
            type="text",
            text=formatter.format_list_payload(
                request=request,
                page=page,
                total_matches=total_matches,
            ),
        )
    ]


async def _handle_get_memory(arguments: dict[str, Any]) -> list[TextContent]:
    formatter = ResultFormatter()
    request = GetMemoryRequest.from_arguments(
        arguments,
        default_project_id=DEFAULT_PROJECT_ID,
    )
    if not request.memory_id:
        return [TextContent(type="text", text="memory_id is required.")]

    item = mem_manager.get_memory_item(
        project_id=request.project_id,
        memory_id=request.memory_id,
    )
    if item is None:
        return [
            TextContent(
                type="text",
                text=formatter.format_memory_not_found(
                    project_id=request.project_id,
                    memory_id=request.memory_id,
                    response_format=request.response_format,
                ),
            )
        ]

    return [
        TextContent(
            type="text",
            text=formatter.format_memory_payload(
                project_id=request.project_id,
                memory_item=item,
                response_format=request.response_format,
            ),
        )
    ]


async def _handle_delete_memory(arguments: dict[str, Any]) -> list[TextContent]:
    request = DeleteMemoryRequest.from_arguments(
        arguments, default_project_id=DEFAULT_PROJECT_ID
    )

    description, _count = mem_manager.delete_memory(request=request)
    return [TextContent(type="text", text=description)]


async def _handle_ingest_repo(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    repo = str(arguments["repo"])
    mode = str(arguments.get("mode") or "mixed")
    tags = normalize_tags(arguments.get("tags"))
    root_override = arguments.get("root") or None
    include_override = normalize_strings(arguments.get("include")) or None
    exclude_override = normalize_strings(arguments.get("exclude")) or None

    manifest = read_manifest(Path(config.manifest_path))
    ingest_config = resolve_repo_config(
        manifest=manifest,
        project_id=project,
        repo=repo,
        root_override=root_override,
        include_override=include_override,
        exclude_override=exclude_override,
    )
    if not ingest_config.root.exists():
        return [TextContent(type="text", text=f"Repo root does not exist: {ingest_config.root}")]

    items = mem_manager.get_all_items(project)
    files = collect_files(ingest_config.root, ingest_config.include, ingest_config.exclude)
    all_tags = sorted(set(ingest_config.default_tags + tags))

    total_deleted = 0
    total_stored = 0
    for file_path in files:
        deleted, stored = ingest_file(
            items=items,
            project_id=project,
            repo=repo,
            path=file_path,
            mode=mode,
            tags=all_tags,
            mem_manager=mem_manager,
        )
        total_deleted += deleted
        total_stored += stored

    return [TextContent(
        type="text",
        text=f"Ingested repo={repo} for project={project}: files={len(files)} deleted={total_deleted} stored={total_stored}",
    )]


async def _handle_ingest_file(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    repo = str(arguments["repo"])
    path = Path(str(arguments["path"])).expanduser().resolve()
    mode = str(arguments.get("mode") or "mixed")
    tags = normalize_tags(arguments.get("tags"))

    if not path.exists():
        return [TextContent(type="text", text=f"File does not exist: {path}")]

    try:
        manifest = read_manifest(Path(config.manifest_path))
        repo_config = resolve_repo_config(
            manifest=manifest,
            project_id=project,
            repo=repo,
            root_override=None,
            include_override=None,
            exclude_override=None,
        )
        tags = sorted(set(repo_config.default_tags + tags))
    except ValueError as exc:
        return [TextContent(type="text", text=str(exc))]

    items = mem_manager.get_all_items(project)
    deleted, stored = ingest_file(
        items=items,
        project_id=project,
        repo=repo,
        path=path,
        mode=mode,
        tags=tags,
        mem_manager=mem_manager,
    )
    return [TextContent(type="text", text=f"Ingested {path}: deleted={deleted} stored={stored}")]


async def _handle_prune_memories(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    repo = arguments.get("repo") or None
    path_prefix = arguments.get("path_prefix") or None
    by = str(arguments.get("by") or "both")

    candidate_items, _ = mem_manager.list_memories(
        ListMemoriesRequest(
            project_id=project,
            repo=repo,
            category=None,
            tag=None,
            path_prefix=path_prefix,
            offset=0,
            limit=GET_ALL_LIMIT,
            response_format="text",
            include_full_text=False,
            excerpt_chars=420,
        )
    )
    fingerprint_deleted = 0
    path_deleted = 0

    if by in {"fingerprint", "both"}:
        groups: dict[str, list] = {}
        for item in candidate_items:
            fp = item.metadata.fingerprint
            if isinstance(fp, str):
                groups.setdefault(fp, []).append(item)
        for group in groups.values():
            if len(group) <= 1:
                continue
            group.sort(key=lambda i: i.metadata.updated_at or "", reverse=True)
            for stale in group[1:]:
                if isinstance(stale.id, str):
                    mem_manager.delete_memory(DeleteMemoryRequest(project_id=project, memory_id=stale.id, upsert_key=None))
                    fingerprint_deleted += 1

    if by in {"path", "both"}:
        for item in candidate_items:
            source_path = item.metadata.source_path
            memory_id = item.id
            if not isinstance(source_path, str) or not isinstance(memory_id, str):
                continue
            if source_path and os.path.isabs(source_path) and not os.path.exists(source_path):
                mem_manager.delete_memory(DeleteMemoryRequest(project_id=project, memory_id=memory_id, upsert_key=None))
                path_deleted += 1

    total = fingerprint_deleted + path_deleted
    return [TextContent(
        type="text",
        text=f"Pruned project={project}: fingerprint={fingerprint_deleted} path={path_deleted} total={total}",
    )]


async def _handle_init_project(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    repos = normalize_strings(arguments.get("repos"))
    description = str(arguments.get("description") or "")
    tags = normalize_tags(arguments.get("tags"))
    set_repo_defaults = bool(arguments.get("set_repo_defaults", False))

    if not repos:
        return [TextContent(type="text", text="repos must include at least one repo name.")]

    try:
        validate_project_id(project)
    except ValueError as exc:
        return [TextContent(type="text", text=f"Invalid project id: {exc}")]

    manifest = read_manifest(Path(config.manifest_path))
    projects = _safe_dict(manifest.get("projects"))
    manifest_repos = _safe_dict(manifest.get("repos"))

    existing = _safe_dict(projects.get(project))
    merged_repos = dedupe_keep_order(normalize_strings(existing.get("repos")) + repos)
    merged_tags = dedupe_keep_order(normalize_tags(existing.get("tags")) + tags or [project])
    projects[project] = {
        "description": description or existing.get("description", ""),
        "tags": merged_tags,
        "repos": merged_repos,
    }

    for repo_name in repos:
        repo_config = _safe_dict(manifest_repos.get(repo_name))
        if not repo_config:
            manifest_repos[repo_name] = {
                "root": guess_repo_root(repo_name),
                "include": list(DEFAULT_INCLUDE),
                "exclude": list(DEFAULT_EXCLUDE),
                "default_tags": [repo_name],
                "default_active_project": project if set_repo_defaults else None,
            }
        elif set_repo_defaults:
            repo_config["default_active_project"] = project
            manifest_repos[repo_name] = repo_config

    manifest["projects"] = projects
    manifest["repos"] = manifest_repos
    write_manifest(Path(config.manifest_path), manifest)

    return [TextContent(
        type="text",
        text=f"Initialized project={project} repos={','.join(repos)}",
    )]


async def _handle_context_plan(arguments: dict[str, Any]) -> list[TextContent]:
    repo = str(arguments["repo"])
    project = arguments.get("project") or None
    pack = str(arguments.get("pack") or "default_3_layer")

    try:
        manifest = read_manifest(Path(config.manifest_path))
        plan = build_context_plan(
            manifest=manifest,
            repo=repo,
            explicit_project=project,
            pack_name=pack,
        )
    except ValueError as exc:
        return [TextContent(type="text", text=str(exc))]

    return [TextContent(type="text", text=json.dumps(plan, indent=2))]


async def _handle_policy_run(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    mode = str(arguments.get("mode") or "dry-run")
    stale_days = max(0, int(arguments.get("stale_days", 45)))
    summary_keep = max(1, int(arguments.get("summary_keep", 5)))
    repo = arguments.get("repo") or None
    path_prefix = arguments.get("path_prefix") or None

    items = mem_manager.get_all_items(project)
    policy = build_policy_actions(
        items=[item.as_dict() for item in items],
        stale_days=stale_days,
        summary_keep=summary_keep,
        repo=repo,
        path_prefix=path_prefix,
    )

    if mode == "dry-run":
        verbose = bool(arguments.get("verbose", False))
        summary = (
            f"Policy run for project={project} mode=dry-run "
            f"scanned={policy['scanned_count']} delete_candidates={policy['delete_count']} "
            f"reason_counts={policy['reasons']}"
        )
        if verbose and policy["delete_ids"]:
            items = mem_manager.get_all_items(project)
            id_to_item = {(item.id or ""): item for item in items}
            detail_lines = [summary, "\nDeletion candidates:"]
            reason_ids = policy.get("reason_ids", {})
            id_to_reason: dict[str, str] = {}
            for reason_name, ids in reason_ids.items():
                for mid in ids:
                    id_to_reason.setdefault(mid, reason_name)
            for mid in policy["delete_ids"]:
                item = id_to_item.get(mid)
                if item:
                    md = item.metadata
                    body_preview = " ".join(item.memory.split())[:120]
                    reason = id_to_reason.get(mid, "unknown")
                    detail_lines.append(
                        f"  [{mid[:8]}] category={md.category or 'n/a'} repo={md.repo or 'n/a'} "
                        f"updated_at={md.updated_at or 'n/a'} reason={reason}\n"
                        f"    {body_preview}..."
                    )
            return [TextContent(type="text", text="\n".join(detail_lines))]
        return [TextContent(type="text", text=summary)]

    deleted = 0
    for memory_id in policy["delete_ids"]:
        mem_manager.delete_memory(
            DeleteMemoryRequest(project_id=project, memory_id=memory_id, upsert_key=None)
        )
        deleted += 1

    return [
        TextContent(
            type="text",
            text=(
                f"Policy run for project={project} mode=apply "
                f"scanned={policy['scanned_count']} delete_candidates={policy['delete_count']} "
                f"deleted={deleted} reason_counts={policy['reasons']}"
            ),
        )
    ]


async def _handle_clear_memories(arguments: dict[str, Any]) -> list[TextContent]:
    project = str(arguments.get("project") or DEFAULT_PROJECT_ID)
    confirm = arguments.get("confirm", False)

    if not confirm:
        return [TextContent(
            type="text",
            text=(
                f"This will delete ALL memories for project={project}. "
                "Pass confirm=true to proceed."
            ),
        )]

    items, _ = mem_manager.list_memories(
        ListMemoriesRequest(
            project_id=project,
            repo=None,
            category=None,
            tag=None,
            path_prefix=None,
            offset=0,
            limit=GET_ALL_LIMIT,
            response_format="text",
            include_full_text=False,
            excerpt_chars=420,
        )
    )
    deleted = 0
    for item in items:
        if isinstance(item.id, str):
            mem_manager.delete_memory(DeleteMemoryRequest(project_id=project, memory_id=item.id, upsert_key=None))
            deleted += 1

    return [TextContent(type="text", text=f"Cleared project={project}: deleted={deleted}")]


async def _handle_update_memory(arguments: dict[str, Any]) -> list[TextContent]:
    request = UpdateMemoryRequest.from_arguments(
        arguments, default_project_id=DEFAULT_PROJECT_ID
    )
    if not request.memory_id:
        return [TextContent(type="text", text="memory_id is required.")]
    if not request.body and request.repo is None and request.category is None and request.tags is None and request.priority is None:
        return [TextContent(type="text", text="Provide at least one field to update: body, repo, category, tags, priority.")]

    found, message = mem_manager.update_memory(request=request)
    return [TextContent(type="text", text=message)]


async def _handle_get_stats(arguments: dict[str, Any]) -> list[TextContent]:
    project_id = str(arguments.get("project_id") or arguments.get("project") or DEFAULT_PROJECT_ID)
    repo = arguments.get("repo") or None

    stats = mem_manager.get_stats(project_id, repo=repo)
    return [TextContent(type="text", text=json.dumps(stats, indent=2, sort_keys=False))]


async def _handle_health_check(arguments: dict[str, Any]) -> list[TextContent]:
    from health import run_health_check, readiness_check, liveness_check
    from constants import OLLAMA_BASE_URL, OLLAMA_MODEL

    probe = str(arguments.get("probe") or "full").lower()
    skip_slow = bool(arguments.get("skip_slow", False))

    if probe == "liveness":
        result = liveness_check()
    elif probe == "readiness":
        result = readiness_check(
            ollama_base_url=OLLAMA_BASE_URL,
            ollama_model=OLLAMA_MODEL,
            reranker_model=config.reranker_model_name,
            default_project_id=DEFAULT_PROJECT_ID,
            chroma_mode=config.chroma_mode,
            chroma_host=config.chroma_host,
            chroma_port=config.chroma_port,
            cache_backend=config.cache_backend,
            redis_url=config.redis_url,
            skip_slow=skip_slow,
            pool_stats=mem_manager.pool_stats(),
            cache_stats=mem_manager.cache_stats(),
        )
    else:
        result = run_health_check(
            ollama_base_url=OLLAMA_BASE_URL,
            ollama_model=OLLAMA_MODEL,
            reranker_model=config.reranker_model_name,
            default_project_id=DEFAULT_PROJECT_ID,
            skip_slow=skip_slow,
        )
    return [TextContent(type="text", text=json.dumps(result, indent=2, sort_keys=False))]


async def _handle_metrics(arguments: dict[str, Any]) -> list[TextContent]:
    """Return operational metrics snapshot."""
    snapshot = METRICS.snapshot()
    snapshot["connection_pool"] = mem_manager.pool_stats()
    snapshot["search_cache"] = mem_manager.cache_stats()
    snapshot["rate_limiter"] = rate_limiter.stats()
    snapshot["access_control"] = access_controller.stats()
    return [TextContent(type="text", text=json.dumps(snapshot, indent=2, sort_keys=False))]


async def _handle_bulk_store_async(arguments: dict[str, Any]) -> list[TextContent]:
    """Async bulk store with concurrency-limited parallelism."""
    project_id = str(arguments.get("project_id") or arguments.get("project") or DEFAULT_PROJECT_ID)
    memories_raw = arguments.get("memories")
    if not isinstance(memories_raw, list) or not memories_raw:
        return [TextContent(type="text", text="memories must be a non-empty list of objects.")]

    results = await mem_manager.bulk_store_async(memories_raw, project_id=project_id)
    ok_count = sum(1 for r in results if r.get("ok"))
    err_count = len(results) - ok_count
    summary = f"bulk_store_async project={project_id}: total={len(results)} ok={ok_count} errors={err_count}"
    detail = json.dumps(results, indent=2)
    return [TextContent(type="text", text=f"{summary}\n{detail}")]


async def _handle_find_similar(arguments: dict[str, Any]) -> list[TextContent]:
    request = FindSimilarRequest.from_arguments(
        arguments, default_project_id=DEFAULT_PROJECT_ID
    )
    if not request.memory_id and not request.text:
        return [TextContent(type="text", text="Provide memory_id or text.")]

    results = mem_manager.find_similar(request=request)
    if not results:
        return [TextContent(type="text", text="No similar memories found.")]

    if request.response_format == "json":
        return [TextContent(type="text", text=json.dumps({"count": len(results), "items": results}, indent=2))]

    lines = [f"Found {len(results)} similar memories for project={request.project_id}:"]
    for idx, item in enumerate(results, start=1):
        score = item.get("score", "n/a")
        score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "n/a"
        md = item.get("metadata", {})
        body_preview = " ".join(str(item.get("memory", "")).split())[:300]
        lines.append(
            f"[{idx}] id={item.get('id')} score={score_text} "
            f"category={md.get('category','general')} repo={md.get('repo','n/a')}\n"
            f"{body_preview}"
        )
    return [TextContent(type="text", text="\n\n".join(lines))]


async def _handle_bulk_store(arguments: dict[str, Any]) -> list[TextContent]:
    project_id = str(arguments.get("project_id") or arguments.get("project") or DEFAULT_PROJECT_ID)
    memories_raw = arguments.get("memories")
    if not isinstance(memories_raw, list) or not memories_raw:
        return [TextContent(type="text", text="memories must be a non-empty list of objects.")]

    results = mem_manager.bulk_store(memories_raw, project_id=project_id)
    ok_count = sum(1 for r in results if r.get("ok"))
    err_count = len(results) - ok_count
    summary = f"bulk_store project={project_id}: total={len(results)} ok={ok_count} errors={err_count}"
    detail = json.dumps(results, indent=2)
    return [TextContent(type="text", text=f"{summary}\n{detail}")]


async def _handle_move_memory(arguments: dict[str, Any]) -> list[TextContent]:
    memory_id = str(arguments.get("memory_id") or "").strip()
    source_project = str(arguments.get("project_id") or DEFAULT_PROJECT_ID)
    target_project = str(arguments.get("target_project_id") or "").strip()
    if not memory_id:
        return [TextContent(type="text", text="memory_id is required.")]
    if not target_project:
        return [TextContent(type="text", text="target_project_id is required.")]

    item = mem_manager.get_memory_item(project_id=source_project, memory_id=memory_id)
    if item is None:
        return [TextContent(type="text", text=f"Memory not found: project={source_project} id={memory_id}")]

    metadata = item.metadata.as_dict()
    metadata["project_id"] = target_project
    from helpers import utc_now
    metadata["updated_at"] = utc_now()

    target_mem = mem_manager.get_memory(target_project)
    result = target_mem.add(item.memory, agent_id=target_project, metadata=metadata, infer=False)
    from helpers import results_from_payload
    stored = results_from_payload(result)
    new_ids = [i.id for i in stored if isinstance(i.id, str)]

    mem_manager.delete_memory(DeleteMemoryRequest(project_id=source_project, memory_id=memory_id, upsert_key=None))

    return [TextContent(
        type="text",
        text=f"Moved memory {memory_id} from project={source_project} to project={target_project} new_ids={','.join(new_ids)}",
    )]


async def _handle_copy_scope(arguments: dict[str, Any]) -> list[TextContent]:
    from_id = str(arguments.get("from_project_id") or "").strip()
    to_id = str(arguments.get("to_project_id") or "").strip()
    dry_run = bool(arguments.get("dry_run", False))

    if not from_id or not to_id:
        return [TextContent(type="text", text="from_project_id and to_project_id are required.")]
    if from_id == to_id:
        return [TextContent(type="text", text="from_project_id and to_project_id must differ.")]

    all_items = mem_manager.get_all_items(from_id)
    if dry_run:
        return [TextContent(
            type="text",
            text=f"copy_scope dry-run: would copy {len(all_items)} memories from project={from_id} to project={to_id}",
        )]

    from helpers import utc_now, results_from_payload
    copied = 0
    errors = 0
    target_mem = mem_manager.get_memory(to_id)
    for raw in all_items:
        from helpers import _coerce_memory_item
        item = _coerce_memory_item(raw)
        metadata = item.metadata.as_dict()
        metadata["project_id"] = to_id
        metadata["updated_at"] = utc_now()
        try:
            target_mem.add(item.memory, agent_id=to_id, metadata=metadata, infer=False)
            copied += 1
        except Exception:
            errors += 1

    return [TextContent(
        type="text",
        text=f"copy_scope from={from_id} to={to_id}: copied={copied} errors={errors}",
    )]


async def _handle_export_scope(arguments: dict[str, Any]) -> list[TextContent]:
    project_id = str(arguments.get("project_id") or arguments.get("project") or DEFAULT_PROJECT_ID)
    fmt = str(arguments.get("format") or "json").lower()

    all_items = mem_manager.get_all_items(project_id)
    lines: list[str] = []
    for raw in all_items:
        from helpers import _coerce_memory_item
        item = _coerce_memory_item(raw)
        lines.append(json.dumps(item.as_dict(), ensure_ascii=False))

    if fmt == "ndjson":
        payload = "\n".join(lines)
    else:
        import json as _json
        payload = _json.dumps([json.loads(line) for line in lines], indent=2)

    return [TextContent(type="text", text=f"Exported {len(lines)} memories from project={project_id}:\n{payload}")]


async def _handle_summarize_scope(arguments: dict[str, Any]) -> list[TextContent]:
    from summarizer import generate_scope_summary
    from constants import OLLAMA_BASE_URL, OLLAMA_MODEL

    project_id = str(arguments.get("project_id") or arguments.get("project") or DEFAULT_PROJECT_ID)
    repo = arguments.get("repo") or None
    category = arguments.get("category") or None
    max_tokens = max(100, min(int(arguments.get("max_tokens", 800)), 2000))

    all_items = mem_manager.get_all_items(project_id)
    summary = generate_scope_summary(
        project_id=project_id,
        items=all_items,
        repo=repo,
        category=category,
        max_tokens=max_tokens,
        ollama_base_url=OLLAMA_BASE_URL,
        ollama_model=OLLAMA_MODEL,
    )
    return [TextContent(type="text", text=f"Summary for project={project_id}:\n\n{summary}")]


# Operations that modify state (need write access check)
_WRITE_OPERATIONS = frozenset({
    "store_memory", "update_memory", "delete_memory", "bulk_store",
    "bulk_store_async", "move_memory", "copy_scope", "clear_memories",
    "ingest_repo", "ingest_file", "prune_memories", "init_project",
    "policy_run",
})

# Map tool names to rate limit operation categories
_RATE_LIMIT_CATEGORIES: dict[str, str] = {
    "search_context": "search",
    "store_memory": "store",
    "bulk_store": "bulk_store",
    "bulk_store_async": "bulk_store",
    "list_memories": "list",
    "delete_memory": "delete",
    "ingest_repo": "ingest",
    "ingest_file": "ingest",
}


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    # Assign a correlation ID for this request
    cid = new_correlation_id()
    METRICS.increment("requests.total")

    # Rate limiting
    if rate_limiter.enabled:
        tenant_id = access_controller.resolve_tenant(arguments)
        rl_key = f"{_RATE_LIMIT_CATEGORIES.get(name, 'default')}:{tenant_id}"
        rl_op = _RATE_LIMIT_CATEGORIES.get(name, "default")
        if not rate_limiter.allow(rl_key, operation=rl_op):
            METRICS.increment("requests.rate_limited")
            wait = rate_limiter.wait_time(rl_key, operation=rl_op)
            return [TextContent(
                type="text",
                text=f"Rate limited. Retry after {wait:.1f}s. correlation_id={cid}",
            )]

    # Access control
    if access_controller.enabled:
        tenant_id = access_controller.resolve_tenant(arguments)
        project_id = str(
            arguments.get("project_id")
            or arguments.get("project")
            or DEFAULT_PROJECT_ID
        )
        if name in _WRITE_OPERATIONS:
            allowed, reason = access_controller.check_write(tenant_id, project_id)
        else:
            allowed, reason = access_controller.check_access(tenant_id, project_id)
        if not allowed:
            METRICS.increment("requests.access_denied")
            return [TextContent(
                type="text",
                text=f"Access denied: {reason}. tenant={tenant_id} project={project_id} correlation_id={cid}",
            )]

    if name == "search_context":
        return await _handle_search_context(arguments)
    elif name == "store_memory":
        return await _handle_store_memory(arguments)
    elif name == "update_memory":
        return await _handle_update_memory(arguments)
    elif name == "list_memories":
        return await _handle_list_memories(arguments)
    elif name == "get_memory":
        return await _handle_get_memory(arguments)
    elif name == "delete_memory":
        return await _handle_delete_memory(arguments)
    elif name == "find_similar":
        return await _handle_find_similar(arguments)
    elif name == "bulk_store":
        return await _handle_bulk_store(arguments)
    elif name == "bulk_store_async":
        return await _handle_bulk_store_async(arguments)
    elif name == "move_memory":
        return await _handle_move_memory(arguments)
    elif name == "copy_scope":
        return await _handle_copy_scope(arguments)
    elif name == "export_scope":
        return await _handle_export_scope(arguments)
    elif name == "get_stats":
        return await _handle_get_stats(arguments)
    elif name == "health_check":
        return await _handle_health_check(arguments)
    elif name == "metrics":
        return await _handle_metrics(arguments)
    elif name == "summarize_scope":
        return await _handle_summarize_scope(arguments)
    elif name == "ingest_repo":
        return await _handle_ingest_repo(arguments)
    elif name == "ingest_file":
        return await _handle_ingest_file(arguments)
    elif name == "prune_memories":
        return await _handle_prune_memories(arguments)
    elif name == "init_project":
        return await _handle_init_project(arguments)
    elif name == "clear_memories":
        return await _handle_clear_memories(arguments)
    elif name == "context_plan":
        return await _handle_context_plan(arguments)
    elif name == "policy_run":
        return await _handle_policy_run(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_context",
            description=(
                "Search scoped memory for architectural context, decisions, and code-aware "
                "summaries. Supports one or many scopes via project_id/project_ids plus "
                "repo/path/category/tag filtering."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_id": {"type": "string"},
                    "project_ids": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                    },
                    "repo": {"type": "string"},
                    "path_prefix": {"type": "string"},
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                    "categories": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                    },
                    "limit": {"type": "integer", "default": 8},
                    "ranking_mode": {
                        "type": "string",
                        "default": config.default_ranking_mode,
                    },
                    "token_budget": {
                        "type": "integer",
                        "default": config.default_token_budget,
                    },
                    "candidate_pool": {"type": "integer"},
                    "rerank_top_n": {
                        "type": "integer",
                        "default": config.default_rerank_top_n,
                    },
                    "debug": {"type": "boolean", "default": False},
                    "response_format": {
                        "type": "string",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                    "include_full_text": {
                        "type": "boolean",
                        "default": False,
                    },
                    "excerpt_chars": {
                        "type": "integer",
                        "default": 420,
                    },
                    "after_date": {
                        "type": "string",
                        "description": "ISO 8601 datetime — only return memories updated after this date",
                    },
                    "before_date": {
                        "type": "string",
                        "description": "ISO 8601 datetime — only return memories updated before this date",
                    },
                    "highlight": {
                        "type": "boolean",
                        "default": False,
                        "description": "Wrap matching query tokens in **bold** in excerpt text",
                    },
                    "search_all_scopes": {
                        "type": "boolean",
                        "default": False,
                        "description": "Search across all manifest scopes (ignores project_id/project_ids)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="store_memory",
            description=(
                "Store structured memory in a scope. Uses project_id as the current scope "
                "identifier and supports metadata fields plus optional upsert behavior via "
                "upsert_key or fingerprint."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "project_id": {"type": "string"},
                    "repo": {"type": "string"},
                    "source_path": {"type": "string"},
                    "source_kind": {"type": "string", "default": "summary"},
                    "category": {"type": "string"},
                    "module": {"type": "string"},
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                    "upsert_key": {"type": "string"},
                    "fingerprint": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "normal", "low"],
                        "default": "normal",
                        "description": "Importance weight used during ranking. high=+20% boost, low=-10% penalty.",
                    },
                    "suggest_tags": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return suggested tags extracted from the body text",
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="update_memory",
            description=(
                "Atomically update an existing memory's body and/or metadata. "
                "Patch semantics: only fields you supply are changed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "body": {"type": "string", "description": "New body text (replaces existing)"},
                    "repo": {"type": "string"},
                    "source_path": {"type": "string"},
                    "source_kind": {"type": "string"},
                    "category": {"type": "string"},
                    "module": {"type": "string"},
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                    "priority": {"type": "string", "enum": ["high", "normal", "low"]},
                },
                "required": ["memory_id"],
            },
        ),
        Tool(
            name="list_memories",
            description=(
                "List stored memories for a selected scope with optional project_id/repo/"
                "category/tag/path filters, pagination, and sort control."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "repo": {"type": "string"},
                    "category": {"type": "string"},
                    "tag": {"type": "string"},
                    "path_prefix": {"type": "string"},
                    "offset": {"type": "integer", "default": 0},
                    "limit": {"type": "integer", "default": 20},
                    "sort_by": {
                        "type": "string",
                        "enum": ["updated_at", "created_at", "category", "repo"],
                        "default": "updated_at",
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "default": "desc",
                    },
                    "response_format": {
                        "type": "string",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                    "include_full_text": {
                        "type": "boolean",
                        "default": False,
                    },
                    "excerpt_chars": {
                        "type": "integer",
                        "default": 420,
                    },
                },
            },
        ),
        Tool(
            name="get_memory",
            description="Fetch a single stored memory by ID, including the full untruncated body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "memory_id": {"type": "string"},
                    "response_format": {
                        "type": "string",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                },
                "required": ["memory_id"],
            },
        ),
        Tool(
            name="delete_memory",
            description=(
                "Delete memory by memory_id, or delete all memories matching an upsert_key "
                "within a selected scope."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "memory_id": {"type": "string"},
                    "upsert_key": {"type": "string"},
                },
            },
        ),
        Tool(
            name="ingest_repo",
            description=(
                "Ingest all files in a repository into scoped memory. The project field "
                "selects the target scope. Existing chunks for each file are replaced."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "repo": {"type": "string"},
                    "root": {"type": "string", "description": "Override the repo root path"},
                    "include": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "description": "Glob patterns to include (overrides manifest defaults)",
                    },
                    "exclude": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "description": "Glob patterns to exclude (overrides manifest defaults)",
                    },
                    "mode": {
                        "type": "string",
                        "default": "mixed",
                        "description": "Chunking mode: docstrings, headings, code-chunks, or mixed",
                    },
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                },
                "required": ["project", "repo"],
            },
        ),
        Tool(
            name="ingest_file",
            description=(
                "Ingest a single file into scoped memory, replacing any existing chunks for "
                "that file. The project field selects the target scope."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string", "description": "Absolute or home-relative path to the file"},
                    "mode": {
                        "type": "string",
                        "default": "mixed",
                        "description": "Chunking mode: docstrings, headings, code-chunks, or mixed",
                    },
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                },
                "required": ["project", "repo", "path"],
            },
        ),
        Tool(
            name="context_plan",
            description=(
                "Preview the resolved layered context payloads for a repo using the configured "
                "manifest and context pack."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "project": {"type": "string"},
                    "pack": {"type": "string", "default": "default_3_layer"},
                },
                "required": ["repo"],
            },
        ),
        Tool(
            name="prune_memories",
            description=(
                "Remove duplicate or stale memories from a selected scope. "
                "Prune by duplicate fingerprint, by missing source paths, or both."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "repo": {"type": "string"},
                    "path_prefix": {"type": "string"},
                    "by": {
                        "type": "string",
                        "enum": ["fingerprint", "path", "both"],
                        "default": "both",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="init_project",
            description=(
                "Initialize or update a scope entry in the memory manifest. "
                "The interface keeps the current project field name and creates the "
                "matching manifest entry plus default repo configurations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "repos": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "description": "Repo names to associate with this project",
                    },
                    "description": {"type": "string"},
                    "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                    "set_repo_defaults": {"type": "boolean", "default": False},
                },
                "required": ["project", "repos"],
            },
        ),
        Tool(
            name="policy_run",
            description=(
                "Run the retention policy for a selected scope in dry-run or apply mode."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["dry-run", "apply"],
                        "default": "dry-run",
                    },
                    "stale_days": {"type": "integer", "default": 45},
                    "summary_keep": {"type": "integer", "default": 5},
                    "repo": {"type": "string"},
                    "path_prefix": {"type": "string"},
                    "verbose": {
                        "type": "boolean",
                        "default": False,
                        "description": "In dry-run mode: show per-memory details (excerpt, reason, age) for each deletion candidate",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="clear_memories",
            description=(
                "Delete ALL memories for a selected scope. "
                "Requires confirm=true to proceed — returns a warning prompt otherwise."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="find_similar",
            description=(
                "Find memories semantically similar to a given text or an existing memory ID. "
                "Useful for dedup review and related-context discovery."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "memory_id": {"type": "string", "description": "ID of seed memory (search from its body)"},
                    "text": {"type": "string", "description": "Raw text to find similar memories for"},
                    "limit": {"type": "integer", "default": 10},
                    "threshold": {
                        "type": "number",
                        "default": 0.0,
                        "description": "Minimum similarity score (0.0–1.0)",
                    },
                    "response_format": {"type": "string", "enum": ["text", "json"], "default": "text"},
                },
            },
        ),
        Tool(
            name="bulk_store",
            description=(
                "Store multiple memories in a single call. "
                "Returns per-item success/error results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "memories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "repo": {"type": "string"},
                                "source_path": {"type": "string"},
                                "source_kind": {"type": "string"},
                                "category": {"type": "string"},
                                "module": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "upsert_key": {"type": "string"},
                                "fingerprint": {"type": "string"},
                                "priority": {"type": "string", "enum": ["high", "normal", "low"]},
                            },
                            "required": ["content"],
                        },
                        "description": "List of memory objects to store",
                    },
                },
                "required": ["memories"],
            },
        ),
        Tool(
            name="get_stats",
            description=(
                "Return aggregate statistics for a scope: total count, breakdown by category/"
                "repo/source_kind/priority, oldest/newest timestamps, estimated token coverage."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "repo": {"type": "string", "description": "Optional repo filter"},
                },
            },
        ),
        Tool(
            name="health_check",
            description=(
                "Check connectivity and readiness of all system components: "
                "Ollama, Chroma, embedding model, reranker, and optional Redis. "
                "Supports liveness/readiness probes for Kubernetes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "probe": {
                        "type": "string",
                        "enum": ["full", "liveness", "readiness"],
                        "default": "full",
                        "description": "Probe type: liveness (fast), readiness (dependencies), full (all)",
                    },
                    "skip_slow": {
                        "type": "boolean",
                        "default": False,
                        "description": "Skip slow model-load checks (embedding + reranker)",
                    },
                },
            },
        ),
        Tool(
            name="metrics",
            description=(
                "Return operational metrics snapshot: request counts, latency "
                "histograms, connection pool stats, cache hit rates, rate limiter "
                "status, and access control violations."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="bulk_store_async",
            description=(
                "Async bulk store with concurrency-limited parallelism. "
                "Faster than bulk_store for large batches (>50 items) as it "
                "processes items concurrently within configurable limits."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "memories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "repo": {"type": "string"},
                                "source_path": {"type": "string"},
                                "source_kind": {"type": "string"},
                                "category": {"type": "string"},
                                "module": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "upsert_key": {"type": "string"},
                                "fingerprint": {"type": "string"},
                                "priority": {"type": "string", "enum": ["high", "normal", "low"]},
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["memories"],
            },
        ),
        Tool(
            name="move_memory",
            description=(
                "Move a single memory from one scope to another. "
                "Re-stores with updated project_id and deletes from source."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "project_id": {"type": "string", "description": "Source scope"},
                    "target_project_id": {"type": "string", "description": "Destination scope"},
                },
                "required": ["memory_id", "target_project_id"],
            },
        ),
        Tool(
            name="copy_scope",
            description=(
                "Copy all memories from one scope to another. "
                "Use dry_run=true to preview without writing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_project_id": {"type": "string"},
                    "to_project_id": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["from_project_id", "to_project_id"],
            },
        ),
        Tool(
            name="export_scope",
            description=(
                "Export all memories for a scope as a JSON array or newline-delimited JSON. "
                "Useful for backup or cross-machine migration."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "format": {
                        "type": "string",
                        "enum": ["json", "ndjson"],
                        "default": "json",
                    },
                },
            },
        ),
        Tool(
            name="summarize_scope",
            description=(
                "Generate a prose summary of what a scope contains, "
                "grouped by category, using the configured LLM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "repo": {"type": "string", "description": "Filter summary to a specific repo"},
                    "category": {"type": "string", "description": "Filter summary to a specific category"},
                    "max_tokens": {"type": "integer", "default": 800},
                },
            },
        ),
    ]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
