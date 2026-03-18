"""consolidate_memories — Find clusters of related memories and optionally consolidate them into summaries. Uses the knowledge graph to find related memories sharing entities."""

from __future__ import annotations

from code_execution.bridge import call_tool


def consolidate_memories(
    category: str | None = None,
    dry_run: bool = True,
    entity: str | None = None,
    project_id: str | None = None,
) -> str:
    """Find clusters of related memories and optionally consolidate them into summaries. Uses the knowledge graph to find related memories sharing entities.

    Args:
        category: Filter clusters to a specific category (optional)
        dry_run: If true, only report what would be consolidated without making changes (optional)
        entity: Find memories related to a specific entity (optional)
        project_id:  (optional)"""
    kwargs: dict = {}
    if category is not None:
        kwargs["category"] = category
    if dry_run is not None:
        kwargs["dry_run"] = dry_run
    if entity is not None:
        kwargs["entity"] = entity
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("consolidate_memories", **kwargs)
