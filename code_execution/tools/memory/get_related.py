"""get_related — Get memories related to a given memory through the knowledge graph. Traverses relationship edges up to max_hops."""

from __future__ import annotations

from code_execution.bridge import call_tool


def get_related(
    memory_id: str,
    *,
    max_hops: int = 1,
    project_id: str | None = None,
    relation_types: list | None = None,
    response_format: str = 'text',
) -> str:
    """Get memories related to a given memory through the knowledge graph. Traverses relationship edges up to max_hops.

    Args:
        memory_id: 
        max_hops: Max traversal depth (1-3) (optional)
        project_id:  (optional)
        relation_types: Filter by relation type (optional)
        response_format:  (one of: 'text', 'json') (optional)"""
    kwargs: dict = {}
    kwargs["memory_id"] = memory_id
    if max_hops is not None:
        kwargs["max_hops"] = max_hops
    if project_id is not None:
        kwargs["project_id"] = project_id
    if relation_types is not None:
        kwargs["relation_types"] = relation_types
    if response_format is not None:
        kwargs["response_format"] = response_format
    return call_tool("get_related", **kwargs)
