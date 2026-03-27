"""clear_memories — Delete ALL memories for a selected scope. Requires confirm=true to proceed — returns a warning prompt otherwise."""

from __future__ import annotations

from code_execution.bridge import call_tool


def clear_memories(
    project: str,
    *,
    confirm: bool = False,
) -> str:
    """Delete ALL memories for a selected scope. Requires confirm=true to proceed — returns a warning prompt otherwise.

    Args:
        project: 
        confirm:  (optional)"""
    kwargs: dict = {}
    kwargs["project"] = project
    if confirm is not None:
        kwargs["confirm"] = confirm
    return call_tool("clear_memories", **kwargs)
