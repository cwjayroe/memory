"""delete_memory — Delete memory by memory_id, or delete all memories matching an upsert_key within a selected scope."""

from __future__ import annotations

from code_execution.bridge import call_tool


def delete_memory(
    memory_id: str | None = None,
    project_id: str | None = None,
    upsert_key: str | None = None,
) -> str:
    """Delete memory by memory_id, or delete all memories matching an upsert_key within a selected scope.

    Args:
        memory_id:  (optional)
        project_id:  (optional)
        upsert_key:  (optional)"""
    kwargs: dict = {}
    if memory_id is not None:
        kwargs["memory_id"] = memory_id
    if project_id is not None:
        kwargs["project_id"] = project_id
    if upsert_key is not None:
        kwargs["upsert_key"] = upsert_key
    return call_tool("delete_memory", **kwargs)
