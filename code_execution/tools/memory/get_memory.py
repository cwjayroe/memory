"""get_memory — Fetch a single stored memory by ID, including the full untruncated body."""

from __future__ import annotations

from code_execution.bridge import call_tool


def get_memory(
    memory_id: str,
    *,
    project_id: str | None = None,
    response_format: str = 'text',
) -> str:
    """Fetch a single stored memory by ID, including the full untruncated body.

    Args:
        memory_id: 
        project_id:  (optional)
        response_format:  (one of: 'text', 'json') (optional)"""
    kwargs: dict = {}
    kwargs["memory_id"] = memory_id
    if project_id is not None:
        kwargs["project_id"] = project_id
    if response_format is not None:
        kwargs["response_format"] = response_format
    return call_tool("get_memory", **kwargs)
