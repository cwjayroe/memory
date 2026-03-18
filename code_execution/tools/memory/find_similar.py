"""find_similar — Find memories semantically similar to a given text or an existing memory ID. Useful for dedup review and related-context discovery."""

from __future__ import annotations

from code_execution.bridge import call_tool


def find_similar(
    limit: int = 10,
    memory_id: str | None = None,
    project_id: str | None = None,
    response_format: str = 'text',
    text: str | None = None,
    threshold: float = 0.0,
) -> str:
    """Find memories semantically similar to a given text or an existing memory ID. Useful for dedup review and related-context discovery.

    Args:
        limit:  (optional)
        memory_id: ID of seed memory (search from its body) (optional)
        project_id:  (optional)
        response_format:  (one of: 'text', 'json') (optional)
        text: Raw text to find similar memories for (optional)
        threshold: Minimum similarity score (0.0–1.0) (optional)"""
    kwargs: dict = {}
    if limit is not None:
        kwargs["limit"] = limit
    if memory_id is not None:
        kwargs["memory_id"] = memory_id
    if project_id is not None:
        kwargs["project_id"] = project_id
    if response_format is not None:
        kwargs["response_format"] = response_format
    if text is not None:
        kwargs["text"] = text
    if threshold is not None:
        kwargs["threshold"] = threshold
    return call_tool("find_similar", **kwargs)
