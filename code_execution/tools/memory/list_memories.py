"""list_memories — List stored memories for a selected scope with optional project_id/repo/category/tag/path filters, pagination, and sort control."""

from __future__ import annotations

from code_execution.bridge import call_tool


def list_memories(
    category: str | None = None,
    excerpt_chars: int = 420,
    include_full_text: bool = False,
    limit: int = 20,
    offset: int = 0,
    path_prefix: str | None = None,
    project_id: str | None = None,
    repo: str | None = None,
    response_format: str = 'text',
    sort_by: str = 'updated_at',
    sort_order: str = 'desc',
    tag: str | None = None,
) -> str:
    """List stored memories for a selected scope with optional project_id/repo/category/tag/path filters, pagination, and sort control.

    Args:
        category:  (optional)
        excerpt_chars:  (optional)
        include_full_text:  (optional)
        limit:  (optional)
        offset:  (optional)
        path_prefix:  (optional)
        project_id:  (optional)
        repo:  (optional)
        response_format:  (one of: 'text', 'json') (optional)
        sort_by:  (one of: 'updated_at', 'created_at', 'category', 'repo') (optional)
        sort_order:  (one of: 'asc', 'desc') (optional)
        tag:  (optional)"""
    kwargs: dict = {}
    if category is not None:
        kwargs["category"] = category
    if excerpt_chars is not None:
        kwargs["excerpt_chars"] = excerpt_chars
    if include_full_text is not None:
        kwargs["include_full_text"] = include_full_text
    if limit is not None:
        kwargs["limit"] = limit
    if offset is not None:
        kwargs["offset"] = offset
    if path_prefix is not None:
        kwargs["path_prefix"] = path_prefix
    if project_id is not None:
        kwargs["project_id"] = project_id
    if repo is not None:
        kwargs["repo"] = repo
    if response_format is not None:
        kwargs["response_format"] = response_format
    if sort_by is not None:
        kwargs["sort_by"] = sort_by
    if sort_order is not None:
        kwargs["sort_order"] = sort_order
    if tag is not None:
        kwargs["tag"] = tag
    return call_tool("list_memories", **kwargs)
