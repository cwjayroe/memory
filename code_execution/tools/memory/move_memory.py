"""move_memory — Move a single memory from one scope to another. Re-stores with updated project_id and deletes from source."""

from __future__ import annotations

from code_execution.bridge import call_tool


def move_memory(
    memory_id: str,
    target_project_id: str,
    *,
    project_id: str | None = None,
) -> str:
    """Move a single memory from one scope to another. Re-stores with updated project_id and deletes from source.

    Args:
        memory_id: 
        target_project_id: Destination scope
        project_id: Source scope (optional)"""
    kwargs: dict = {}
    kwargs["memory_id"] = memory_id
    kwargs["target_project_id"] = target_project_id
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("move_memory", **kwargs)
