"""link_memories — Create an explicit relationship between two memories. Supported relations: supersedes, implements, depends_on, related_to, contradicts, refines."""

from __future__ import annotations

from code_execution.bridge import call_tool


def link_memories(
    source_id: str,
    target_id: str,
    *,
    confidence: float = 1.0,
    project_id: str | None = None,
    relation: str = 'related_to',
) -> str:
    """Create an explicit relationship between two memories. Supported relations: supersedes, implements, depends_on, related_to, contradicts, refines.

    Args:
        source_id: Source memory ID
        target_id: Target memory ID
        confidence: Confidence score 0.0-1.0 (optional)
        project_id:  (optional)
        relation:  (one of: 'supersedes', 'implements', 'depends_on', 'related_to', 'contradicts', 'refines') (optional)"""
    kwargs: dict = {}
    kwargs["source_id"] = source_id
    kwargs["target_id"] = target_id
    if confidence is not None:
        kwargs["confidence"] = confidence
    if project_id is not None:
        kwargs["project_id"] = project_id
    if relation is not None:
        kwargs["relation"] = relation
    return call_tool("link_memories", **kwargs)
