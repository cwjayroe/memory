"""bulk_store — Store multiple memories in a single call. Returns per-item success/error results."""

from __future__ import annotations

from code_execution.bridge import call_tool


def bulk_store(
    memories: list,
    *,
    project_id: str | None = None,
) -> str:
    """Store multiple memories in a single call. Returns per-item success/error results.

    Args:
        memories: List of memory objects to store
        project_id:  (optional)"""
    kwargs: dict = {}
    kwargs["memories"] = memories
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("bulk_store", **kwargs)
