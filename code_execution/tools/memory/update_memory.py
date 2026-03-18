"""update_memory — Atomically update an existing memory's body and/or metadata. Patch semantics: only fields you supply are changed."""

from __future__ import annotations

from code_execution.bridge import call_tool


def update_memory(
    memory_id: str,
    *,
    body: str | None = None,
    category: str | None = None,
    module: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    repo: str | None = None,
    source_kind: str | None = None,
    source_path: str | None = None,
    tags: list | str | None = None,
) -> str:
    """Atomically update an existing memory's body and/or metadata. Patch semantics: only fields you supply are changed.

    Args:
        memory_id: 
        body: New body text (replaces existing) (optional)
        category:  (optional)
        module:  (optional)
        priority:  (one of: 'high', 'normal', 'low') (optional)
        project_id:  (optional)
        repo:  (optional)
        source_kind:  (optional)
        source_path:  (optional)
        tags:  (optional)"""
    kwargs: dict = {}
    kwargs["memory_id"] = memory_id
    if body is not None:
        kwargs["body"] = body
    if category is not None:
        kwargs["category"] = category
    if module is not None:
        kwargs["module"] = module
    if priority is not None:
        kwargs["priority"] = priority
    if project_id is not None:
        kwargs["project_id"] = project_id
    if repo is not None:
        kwargs["repo"] = repo
    if source_kind is not None:
        kwargs["source_kind"] = source_kind
    if source_path is not None:
        kwargs["source_path"] = source_path
    if tags is not None:
        kwargs["tags"] = tags
    return call_tool("update_memory", **kwargs)
