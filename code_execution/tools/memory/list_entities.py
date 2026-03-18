"""list_entities — List known entities extracted from memories in this scope."""

from __future__ import annotations

from code_execution.bridge import call_tool


def list_entities(
    kind: str | None = None,
    limit: int = 50,
    project_id: str | None = None,
    response_format: str = 'text',
) -> str:
    """List known entities extracted from memories in this scope.

    Args:
        kind: Filter by entity kind: service, api, module, pattern, concept, tool, file (optional)
        limit:  (optional)
        project_id:  (optional)
        response_format:  (one of: 'text', 'json') (optional)"""
    kwargs: dict = {}
    if kind is not None:
        kwargs["kind"] = kind
    if limit is not None:
        kwargs["limit"] = limit
    if project_id is not None:
        kwargs["project_id"] = project_id
    if response_format is not None:
        kwargs["response_format"] = response_format
    return call_tool("list_entities", **kwargs)
