"""search_by_entity — Find all memories that mention a specific entity."""

from __future__ import annotations

from code_execution.bridge import call_tool


def search_by_entity(
    entity_name: str,
    *,
    entity_kind: str | None = None,
    project_id: str | None = None,
    response_format: str = 'text',
) -> str:
    """Find all memories that mention a specific entity.

    Args:
        entity_name: 
        entity_kind:  (optional)
        project_id:  (optional)
        response_format:  (one of: 'text', 'json') (optional)"""
    kwargs: dict = {}
    kwargs["entity_name"] = entity_name
    if entity_kind is not None:
        kwargs["entity_kind"] = entity_kind
    if project_id is not None:
        kwargs["project_id"] = project_id
    if response_format is not None:
        kwargs["response_format"] = response_format
    return call_tool("search_by_entity", **kwargs)
