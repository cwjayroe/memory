"""Project-scoped, repo-aware memory server for Cursor via MCP."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from memory_types import (
    DeleteMemoryRequest,
    GetMemoryRequest,
    ListMemoriesRequest,
    SearchContextParsePolicy,
    SearchContextRequest,
    StoreMemoryRequest,
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
from ingest import ingest_file, collect_files
from manifest import (
    resolve_repo_config,
    read_manifest,
    write_manifest,
    validate_project_id,
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    guess_repo_root,
)

LOGGER = logging.getLogger(__name__)
config = ServerConfig.from_env()
app = Server("project-memory")
scoring_engine = ScoringEngine(
    reranker=RerankerManager(config.reranker_model_name),
)
mem_manager = MemoryManager(config=config, scoring_engine=scoring_engine, logger=LOGGER)


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
        f"deleted_existing={deleted_count} new_ids={','.join(new_ids) if new_ids else 'n/a'}"
    )
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
                "default_active_project": project,
            }

    manifest["projects"] = projects
    manifest["repos"] = manifest_repos
    write_manifest(Path(config.manifest_path), manifest)

    return [TextContent(
        type="text",
        text=f"Initialized project={project} repos={','.join(repos)}",
    )]


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


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search_context":
        return await _handle_search_context(arguments)
    elif name == "store_memory":
        return await _handle_store_memory(arguments)
    elif name == "list_memories":
        return await _handle_list_memories(arguments)
    elif name == "get_memory":
        return await _handle_get_memory(arguments)
    elif name == "delete_memory":
        return await _handle_delete_memory(arguments)
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
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_context",
            description=(
                "Search project memory for architectural context, decisions, and code-aware "
                "summaries. Supports one or many projects plus repo/path/category/tag filtering."
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
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="store_memory",
            description=(
                "Store structured memory for a project. Supports metadata fields and optional "
                "upsert behavior via upsert_key or fingerprint."
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
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="list_memories",
            description="List stored memories with optional project/repo/category/tag/path filters and pagination.",
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
                "within a project."
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
                "Ingest all files in a repository into project memory. Chunks each file and "
                "stores the results, replacing any existing chunks for each file."
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
            description="Ingest a single file into project memory, replacing any existing chunks for that file.",
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
            name="prune_memories",
            description=(
                "Remove duplicate or stale memories from a project. "
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
                "Initialize or update a project in the memory manifest. "
                "Creates the project entry and default repo configurations."
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
                },
                "required": ["project", "repos"],
            },
        ),
        Tool(
            name="clear_memories",
            description=(
                "Delete ALL memories for a project. "
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
    ]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
