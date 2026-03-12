#!/usr/bin/env python3
"""Manual ingestion CLI for scoped, repo-aware memory."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mem0 import Memory
from chunking import (
    MAX_CHARS,
    OVERLAP_CHARS,
    chunk_file
)
from constants import GET_ALL_LIMIT
from memory_types import (
    ClearRequest,
    ContextPlanRequest,
    DeleteMemoryRequest,
    FileIngestRequest,
    IngestListRequest,
    ListMemoriesRequest,
    NoteRequest,
    PolicyRunRequest,
    ProjectInitRequest,
    PruneRequest,
    RepoIngestRequest,
    StoreMemoryRequest,
)
from memory_manager import MemoryManager
from manifest import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    build_context_plan,
    guess_repo_root,
    read_manifest,
    resolve_repo_config,
    validate_project_id,
    write_manifest,
)
from helpers import (
    dedupe_keep_order as _dedupe_keep_order,
    get_all_items,
    normalize_strings,
    normalize_tags,
    parse_datetime as _parse_datetime,
    safe_dict as _safe_dict,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path(__file__).with_name("projects.yaml")

_MEM_MANAGER: MemoryManager | None = None


def _get_mem_manager() -> MemoryManager:
    global _MEM_MANAGER
    if _MEM_MANAGER is None:
        _MEM_MANAGER = MemoryManager(logger=LOGGER)
    return _MEM_MANAGER


@dataclass(frozen=True)
class IngestConfig:
    max_chars: int = MAX_CHARS
    overlap_chars: int = OVERLAP_CHARS
    default_manifest: Path = DEFAULT_MANIFEST


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def should_include(path: Path, root: Path, include: list[str], exclude: list[str]) -> bool:
    rel = path.relative_to(root).as_posix()
    if include and not any(fnmatch.fnmatch(rel, pattern) for pattern in include):
        return False
    if exclude and any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
        return False
    return True


def collect_files(root: Path, include: list[str], exclude: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_include(path, root, include, exclude):
            files.append(path)
    return sorted(files)


def memory_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def ingest_file(
    *,
    items: list[dict[str, Any]],
    project_id: str,
    repo: str,
    path: Path,
    mode: str,
    tags: list[str],
    mem_manager: "MemoryManager | None" = None,
) -> tuple[int, int]:
    mm = mem_manager or _get_mem_manager()
    source_path = str(path.resolve())

    # Delete all existing chunks for this source path before re-ingesting.
    path_items = [
        item for item in items
        if memory_metadata(item).get("repo") == repo
        and memory_metadata(item).get("source_path") == source_path
    ]
    deleted = 0
    for item in path_items:
        memory_id = item.get("id")
        if isinstance(memory_id, str):
            mm.delete_memory(DeleteMemoryRequest(project_id=project_id, memory_id=memory_id, upsert_key=None))
            deleted += 1
            items.remove(item)

    chunks = chunk_file(path, mode)
    stored = 0
    for index, chunk in enumerate(chunks):
        upsert_key = "::".join([project_id, repo or "global", source_path or "adhoc", chunk.source_kind, str(index)])
        _, stored_ids = mm.store_memory(
            StoreMemoryRequest(
                project_id=project_id,
                content=chunk.content,
                repo=repo,
                source_path=source_path,
                source_kind=chunk.source_kind,
                category=chunk.category,
                module=chunk.module,
                tags=tags,
                upsert_key=upsert_key,
                fingerprint=sha256_text(chunk.content),
            ),
            pre_fetched_items=items,
        )
        stored += len(stored_ids)
    return deleted, stored


def _summary_topic_key(item: dict[str, Any]) -> str:
    metadata = memory_metadata(item)
    for key in ("upsert_key", "module", "source_path"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    text = " ".join(str(item.get("memory", "")).lower().split())
    seed = " ".join(text.split()[:12])
    return f"summary::{sha256_text(seed or str(item.get('id', 'unknown')))[:16]}"


def build_policy_actions(
    *,
    items: list[dict[str, Any]],
    stale_days: int,
    summary_keep: int,
    repo: str | None = None,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    protected_categories = {"decision", "architecture"}

    filtered: list[dict[str, Any]] = []
    for item in items:
        metadata = memory_metadata(item)
        if repo and metadata.get("repo") != repo:
            continue
        if path_prefix:
            source_path = metadata.get("source_path")
            if not isinstance(source_path, str) or not source_path.startswith(path_prefix):
                continue
        filtered.append(item)

    delete_ids: set[str] = set()
    reasons: dict[str, list[str]] = {
        "summary_over_limit": [],
        "code_doc_stale": [],
        "code_doc_duplicate_fingerprint": [],
    }

    summary_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in filtered:
        metadata = memory_metadata(item)
        if metadata.get("category") != "summary":
            continue
        repo_name = str(metadata.get("repo") or "n/a")
        topic = _summary_topic_key(item)
        summary_groups.setdefault((repo_name, topic), []).append(item)

    for group_items in summary_groups.values():
        group_items.sort(key=lambda x: memory_metadata(x).get("updated_at", ""), reverse=True)
        for stale in group_items[summary_keep:]:
            memory_id = stale.get("id")
            if isinstance(memory_id, str):
                delete_ids.add(memory_id)
                reasons["summary_over_limit"].append(memory_id)

    code_doc_items = [
        item
        for item in filtered
        if memory_metadata(item).get("category") in {"code", "documentation"}
    ]

    fingerprint_groups: dict[str, list[dict[str, Any]]] = {}
    for item in code_doc_items:
        fingerprint = memory_metadata(item).get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint.strip():
            fingerprint_groups.setdefault(fingerprint, []).append(item)

    for group_items in fingerprint_groups.values():
        group_items.sort(key=lambda x: memory_metadata(x).get("updated_at", ""), reverse=True)
        for stale in group_items[1:]:
            memory_id = stale.get("id")
            if isinstance(memory_id, str):
                delete_ids.add(memory_id)
                reasons["code_doc_duplicate_fingerprint"].append(memory_id)

    stale_seconds = max(stale_days, 0) * 86400
    for item in code_doc_items:
        memory_id = item.get("id")
        if not isinstance(memory_id, str):
            continue
        updated_at = _parse_datetime(memory_metadata(item).get("updated_at"))
        if updated_at is None:
            continue
        age = (now_utc - updated_at).total_seconds()
        if age > stale_seconds:
            delete_ids.add(memory_id)
            reasons["code_doc_stale"].append(memory_id)

    protected_ids: set[str] = set()
    for item in filtered:
        metadata = memory_metadata(item)
        category = metadata.get("category")
        memory_id = item.get("id")
        if category in protected_categories and isinstance(memory_id, str):
            protected_ids.add(memory_id)

    final_ids = sorted(delete_ids - protected_ids)

    return {
        "delete_ids": final_ids,
        "delete_count": len(final_ids),
        "scanned_count": len(filtered),
        "reasons": {key: len(values) for key, values in reasons.items()},
    }


# ---------------------------------------------------------------------------
# Session helpers (load memory + all items in one call)
# ---------------------------------------------------------------------------


def _load_memory_session(project_id: str) -> tuple[Memory, list[dict[str, Any]]]:
    memory = _get_mem_manager().get_memory(project_id)
    items = get_all_items(memory, project_id)
    return memory, items



# ---------------------------------------------------------------------------
# Command handlers (thin wrappers: parse request -> delegate -> print output)
# ---------------------------------------------------------------------------


def _run_repo_ingest(request: RepoIngestRequest) -> None:
    manifest = read_manifest(request.manifest_path)
    config = resolve_repo_config(
        manifest=manifest,
        project_id=request.project,
        repo=request.repo,
        root_override=request.root_override,
        include_override=request.include_override,
        exclude_override=request.exclude_override,
    )
    if not config.root.exists():
        raise FileNotFoundError(f"Repo root does not exist: {config.root}")

    _, items = _load_memory_session(request.project)
    files = collect_files(config.root, config.include, config.exclude)
    tags = sorted(set(config.default_tags + request.tags))

    LOGGER.info("→ Project: %s", request.project)
    LOGGER.info("→ Repo: %s", request.repo)
    LOGGER.info("→ Root: %s", config.root)
    LOGGER.info("→ Mode: %s", request.mode)
    LOGGER.info("→ Files matched: %d", len(files))

    total_deleted = 0
    total_stored = 0
    for file_path in files:
        deleted, stored = ingest_file(
            items=items,
            project_id=request.project,
            repo=request.repo,
            path=file_path,
            mode=request.mode,
            tags=tags,
        )
        total_deleted += deleted
        total_stored += stored
        LOGGER.info("  ✓ %s: deleted=%d stored=%d", file_path, deleted, stored)
    LOGGER.info("Done. deleted=%d stored=%d", total_deleted, total_stored)


def _run_file_ingest(request: FileIngestRequest) -> None:
    if not request.path.exists():
        raise FileNotFoundError(f"File not found: {request.path}")

    tags = list(request.tags)
    try:
        manifest = read_manifest(DEFAULT_MANIFEST)
        repo_config = resolve_repo_config(
            manifest=manifest,
            project_id=request.project,
            repo=request.repo,
            root_override=None,
            include_override=None,
            exclude_override=None,
        )
        tags = sorted(set(repo_config.default_tags + request.tags))
    except Exception:
        LOGGER.warning(
            "Falling back to explicit tags only for file ingest project=%s repo=%s",
            request.project,
            request.repo,
            exc_info=True,
        )

    _, items = _load_memory_session(request.project)
    deleted, stored = ingest_file(
        items=items,
        project_id=request.project,
        repo=request.repo,
        path=request.path,
        mode=request.mode,
        tags=tags,
    )
    LOGGER.info("Done. %s deleted=%d stored=%d", request.path, deleted, stored)


def _run_note_ingest(request: NoteRequest) -> None:
    if not request.text:
        raise ValueError("Note text cannot be empty")
    mm = _get_mem_manager()
    upsert_key = "::".join([request.project, request.repo or "global", request.source_path or "adhoc", request.source_kind, "0"])
    _, stored_ids = mm.store_memory(
        StoreMemoryRequest(
            project_id=request.project,
            content=request.text,
            repo=request.repo,
            source_path=request.source_path,
            source_kind=request.source_kind,
            category=request.category,
            module=None,
            tags=request.tags,
            upsert_key=upsert_key,
            fingerprint=sha256_text(request.text),
        )
    )
    LOGGER.info("Stored note memories: %d", len(stored_ids))


def _run_list_memories(request: IngestListRequest) -> None:
    mm = _get_mem_manager()
    page, total = mm.list_memories(
        ListMemoriesRequest(
            project_id=request.project,
            repo=request.repo,
            category=request.category,
            tag=request.tag,
            path_prefix=request.path_prefix,
            offset=request.offset,
            limit=request.limit,
            response_format="text",
            include_full_text=False,
            excerpt_chars=420,
        )
    )
    if not page:
        LOGGER.info("No memories found for filters.")
        return
    LOGGER.info(
        "Project=%s total_matches=%d offset=%d limit=%d returned=%d",
        request.project, total, request.offset, request.limit, len(page),
    )
    for item in page:
        md = item.metadata
        LOGGER.info(
            "id=%s repo=%s category=%s source_kind=%s",
            item.id, md.repo, md.category, md.source_kind,
        )
        LOGGER.info("path=%s updated_at=%s", md.source_path, md.updated_at)
        LOGGER.info("tags=%s", ",".join(normalize_tags(md.tags)))
        LOGGER.info("-" * 80)
        LOGGER.info("%s", item.memory)
        LOGGER.info("=" * 80)


def _run_prune_memories(request: PruneRequest) -> None:
    mm = _get_mem_manager()
    candidate_items, _ = mm.list_memories(
        ListMemoriesRequest(
            project_id=request.project,
            repo=request.repo,
            category=None,
            tag=None,
            path_prefix=request.path_prefix,
            offset=0,
            limit=GET_ALL_LIMIT,
            response_format="text",
            include_full_text=False,
            excerpt_chars=420,
        )
    )
    deleted = 0

    if request.by in {"fingerprint", "both"}:
        groups: dict[str, list] = {}
        for item in candidate_items:
            fingerprint = item.metadata.fingerprint
            if not isinstance(fingerprint, str):
                continue
            groups.setdefault(fingerprint, []).append(item)
        for group in groups.values():
            if len(group) <= 1:
                continue
            group.sort(key=lambda item: item.metadata.updated_at or "", reverse=True)
            for stale in group[1:]:
                if isinstance(stale.id, str):
                    mm.delete_memory(DeleteMemoryRequest(project_id=request.project, memory_id=stale.id, upsert_key=None))
                    deleted += 1
        LOGGER.info("Pruned duplicate fingerprints: %d", deleted)

    if request.by in {"path", "both"}:
        path_deleted = 0
        for item in candidate_items:
            source_path = item.metadata.source_path
            memory_id = item.id
            if not isinstance(source_path, str) or not isinstance(memory_id, str):
                continue
            if source_path and os.path.isabs(source_path) and not os.path.exists(source_path):
                mm.delete_memory(DeleteMemoryRequest(project_id=request.project, memory_id=memory_id, upsert_key=None))
                path_deleted += 1
        deleted += path_deleted
        LOGGER.info("Pruned stale source paths: %d", path_deleted)

    LOGGER.info("Total pruned: %d", deleted)


def _run_clear_memories(request: ClearRequest) -> None:
    mm = _get_mem_manager()
    confirm = input(f"Delete ALL memories for project '{request.project}'? [y/N] ")
    if confirm.lower() != "y":
        LOGGER.info("Cancelled")
        return
    items, _ = mm.list_memories(
        ListMemoriesRequest(
            project_id=request.project,
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
            mm.delete_memory(DeleteMemoryRequest(project_id=request.project, memory_id=item.id, upsert_key=None))
            deleted += 1
    LOGGER.info("Deleted %d memories.", deleted)


def _run_project_init(request: ProjectInitRequest) -> None:
    validate_project_id(request.project)
    manifest = read_manifest(request.manifest_path)
    projects = _safe_dict(manifest.get("projects"))
    repos = _safe_dict(manifest.get("repos"))

    if not request.repos:
        raise ValueError("--repos must include at least one repo name")

    existing = _safe_dict(projects.get(request.project))
    merged_repos = _dedupe_keep_order(normalize_strings(existing.get("repos")) + request.repos)
    merged_tags = _dedupe_keep_order(normalize_tags(existing.get("tags")) + request.tags or [request.project])
    projects[request.project] = {
        "description": request.description or existing.get("description", ""),
        "tags": merged_tags,
        "repos": merged_repos,
    }

    for repo_name in request.repos:
        repo_config = _safe_dict(repos.get(repo_name))
        if not repo_config:
            repos[repo_name] = {
                "root": guess_repo_root(repo_name),
                "include": list(DEFAULT_INCLUDE),
                "exclude": list(DEFAULT_EXCLUDE),
                "default_tags": [repo_name],
                "default_active_project": request.project if request.set_repo_defaults else None,
            }
        elif request.set_repo_defaults:
            repo_config["default_active_project"] = request.project
            repos[repo_name] = repo_config

    manifest["projects"] = projects
    manifest["repos"] = repos
    write_manifest(request.manifest_path, manifest)

    LOGGER.info("Updated manifest: %s", request.manifest_path)
    LOGGER.info("project=%s", request.project)
    LOGGER.info("repos=%s", ",".join(request.repos))
    LOGGER.info("set_repo_defaults=%s", request.set_repo_defaults)


def _run_context_plan(request: ContextPlanRequest) -> None:
    manifest = read_manifest(request.manifest_path)
    plan = build_context_plan(
        manifest=manifest,
        repo=request.repo,
        explicit_project=request.project,
        pack_name=request.pack,
    )
    LOGGER.info((json.dumps(plan, indent=2)))


def _run_policy(request: PolicyRunRequest) -> None:
    _memory, items = _load_memory_session(request.project)
    policy = build_policy_actions(
        items=items,
        stale_days=request.stale_days,
        summary_keep=request.summary_keep,
        repo=request.repo,
        path_prefix=request.path_prefix,
    )
    LOGGER.info(
        "Policy run for project=%s mode=%s scanned=%d delete_candidates=%d",
        request.project, request.mode, policy["scanned_count"], policy["delete_count"],
    )
    LOGGER.info("reason_counts=%s", policy["reasons"])
    if request.mode == "dry-run":
        LOGGER.info("No deletions applied (dry-run).")
        if policy["delete_ids"]:
            preview = ",".join(policy["delete_ids"][:20])
            LOGGER.info("candidate_ids_preview=%s", preview)
        return
    mm = _get_mem_manager()
    deleted = 0
    for memory_id in policy["delete_ids"]:
        mm.delete_memory(DeleteMemoryRequest(project_id=request.project, memory_id=memory_id, upsert_key=None))
        deleted += 1
    LOGGER.info("Applied policy deletions: %d", deleted)


# ---------------------------------------------------------------------------
# Argparse command dispatchers
# ---------------------------------------------------------------------------


def cmd_repo(args: argparse.Namespace) -> None:
    _run_repo_ingest(RepoIngestRequest.from_namespace(args))


def cmd_file(args: argparse.Namespace) -> None:
    _run_file_ingest(FileIngestRequest.from_namespace(args))


def cmd_note(args: argparse.Namespace) -> None:
    _run_note_ingest(NoteRequest.from_namespace(args))


def cmd_list(args: argparse.Namespace) -> None:
    _run_list_memories(IngestListRequest.from_namespace(args))


def cmd_prune(args: argparse.Namespace) -> None:
    _run_prune_memories(PruneRequest.from_namespace(args))


def cmd_clear(args: argparse.Namespace) -> None:
    _run_clear_memories(ClearRequest.from_namespace(args))


def cmd_project_init(args: argparse.Namespace) -> None:
    _run_project_init(ProjectInitRequest.from_namespace(args))


def cmd_context_plan(args: argparse.Namespace) -> None:
    _run_context_plan(ContextPlanRequest.from_namespace(args))


def cmd_policy_run(args: argparse.Namespace) -> None:
    _run_policy(PolicyRunRequest.from_namespace(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project memory ingestion CLI")
    parser.set_defaults(func=None)
    sub = parser.add_subparsers(dest="command")

    repo_cmd = sub.add_parser("repo", help="Ingest an entire repo into a selected scope")
    repo_cmd.add_argument("--project", required=True)
    repo_cmd.add_argument("--repo", required=True)
    repo_cmd.add_argument("--root")
    repo_cmd.add_argument("--mode", choices=["docstrings", "headings", "code-chunks", "mixed"], default="mixed")
    repo_cmd.add_argument("--include", action="append")
    repo_cmd.add_argument("--exclude", action="append")
    repo_cmd.add_argument("--tags")
    repo_cmd.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    repo_cmd.set_defaults(func=cmd_repo)

    file_cmd = sub.add_parser("file", help="Ingest a single file into a selected scope")
    file_cmd.add_argument("--project", required=True)
    file_cmd.add_argument("--repo", required=True)
    file_cmd.add_argument("--path", required=True)
    file_cmd.add_argument("--mode", choices=["docstrings", "headings", "code-chunks", "mixed"], default="mixed")
    file_cmd.add_argument("--tags")
    file_cmd.set_defaults(func=cmd_file)

    note_cmd = sub.add_parser("note", help="Store a decision or note in a selected scope")
    note_cmd.add_argument("--project", required=True)
    note_cmd.add_argument("--text", required=True)
    note_cmd.add_argument("--repo")
    note_cmd.add_argument("--source-path")
    note_cmd.add_argument("--source-kind", default="summary")
    note_cmd.add_argument("--category", default="summary")
    note_cmd.add_argument("--tags")
    note_cmd.set_defaults(func=cmd_note)

    list_cmd = sub.add_parser("list", help="List memories for a selected scope")
    list_cmd.add_argument("--project", required=True)
    list_cmd.add_argument("--repo")
    list_cmd.add_argument("--category")
    list_cmd.add_argument("--tag")
    list_cmd.add_argument("--path-prefix")
    list_cmd.add_argument("--offset", type=int, default=0)
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.set_defaults(func=cmd_list)

    prune_cmd = sub.add_parser("prune", help="Prune duplicate or stale entries in a selected scope")
    prune_cmd.add_argument("--project", required=True)
    prune_cmd.add_argument("--repo")
    prune_cmd.add_argument("--path-prefix")
    prune_cmd.add_argument("--by", choices=["fingerprint", "path", "both"], default="both")
    prune_cmd.set_defaults(func=cmd_prune)

    clear_cmd = sub.add_parser("clear", help="Delete all memories for a selected scope")
    clear_cmd.add_argument("--project", required=True)
    clear_cmd.set_defaults(func=cmd_clear)

    project_init_cmd = sub.add_parser("project-init", help="Create or update a scope entry in manifest v2")
    project_init_cmd.add_argument("--project", required=True)
    project_init_cmd.add_argument("--repos", required=True, help="Comma-separated repo names")
    project_init_cmd.add_argument("--description", default="")
    project_init_cmd.add_argument("--tags")
    project_init_cmd.add_argument("--set-repo-defaults", action="store_true")
    project_init_cmd.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    project_init_cmd.set_defaults(func=cmd_project_init)

    context_plan_cmd = sub.add_parser("context-plan", help="Print resolved 3-layer context payloads")
    context_plan_cmd.add_argument("--repo", required=True)
    context_plan_cmd.add_argument("--project")
    context_plan_cmd.add_argument("--pack", default="default_3_layer")
    context_plan_cmd.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    context_plan_cmd.set_defaults(func=cmd_context_plan)

    policy_cmd = sub.add_parser("policy-run", help="Run tiered retention policy for a selected scope")
    policy_cmd.add_argument("--project", required=True)
    policy_cmd.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    policy_cmd.add_argument("--stale-days", type=int, default=45)
    policy_cmd.add_argument("--summary-keep", type=int, default=5)
    policy_cmd.add_argument("--repo")
    policy_cmd.add_argument("--path-prefix")
    policy_cmd.set_defaults(func=cmd_policy_run)

    return parser


COMMAND_HANDLERS = {
    "repo": cmd_repo,
    "file": cmd_file,
    "note": cmd_note,
    "list": cmd_list,
    "prune": cmd_prune,
    "clear": cmd_clear,
    "project-init": cmd_project_init,
    "context-plan": cmd_context_plan,
    "policy-run": cmd_policy_run,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = COMMAND_HANDLERS.get(args.command or "")
    if handler is None:
        parser.print_help()
        return
    handler(args)


if __name__ == "__main__":
    main()
