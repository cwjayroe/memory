"""store_memory — Store structured memory in a scope. Uses project_id as the current scope identifier and supports metadata fields plus optional upsert behavior via upsert_key or fingerprint."""

from __future__ import annotations

from code_execution.bridge import call_tool


def store_memory(
    content: str,
    *,
    category: str | None = None,
    fingerprint: str | None = None,
    module: str | None = None,
    priority: str = 'normal',
    project_id: str | None = None,
    repo: str | None = None,
    source_kind: str = 'summary',
    source_path: str | None = None,
    suggest_tags: bool = False,
    tags: list | str | None = None,
    upsert_key: str | None = None,
) -> str:
    """Store structured memory in a scope. Uses project_id as the current scope identifier and supports metadata fields plus optional upsert behavior via upsert_key or fingerprint.

    Args:
        content: 
        category:  (optional)
        fingerprint:  (optional)
        module:  (optional)
        priority: Importance weight used during ranking. high=+20% boost, low=-10% penalty. (one of: 'high', 'normal', 'low') (optional)
        project_id:  (optional)
        repo:  (optional)
        source_kind:  (optional)
        source_path:  (optional)
        suggest_tags: Return suggested tags extracted from the body text (optional)
        tags:  (optional)
        upsert_key:  (optional)"""
    kwargs: dict = {}
    kwargs["content"] = content
    if category is not None:
        kwargs["category"] = category
    if fingerprint is not None:
        kwargs["fingerprint"] = fingerprint
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
    if suggest_tags is not None:
        kwargs["suggest_tags"] = suggest_tags
    if tags is not None:
        kwargs["tags"] = tags
    if upsert_key is not None:
        kwargs["upsert_key"] = upsert_key
    return call_tool("store_memory", **kwargs)
