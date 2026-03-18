"""extract_entities — Extract and link entities from a specific memory or all memories in scope. Builds the knowledge graph."""

from __future__ import annotations

from code_execution.bridge import call_tool


def extract_entities(
    memory_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Extract and link entities from a specific memory or all memories in scope. Builds the knowledge graph.

    Args:
        memory_id: Specific memory to extract from. If omitted, processes all memories. (optional)
        project_id:  (optional)"""
    kwargs: dict = {}
    if memory_id is not None:
        kwargs["memory_id"] = memory_id
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("extract_entities", **kwargs)
