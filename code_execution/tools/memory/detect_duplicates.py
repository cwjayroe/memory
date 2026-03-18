"""detect_duplicates — Find near-duplicate memories using text similarity. Reports groups of memories with >92% similarity."""

from __future__ import annotations

from code_execution.bridge import call_tool


def detect_duplicates(
    category: str | None = None,
    project_id: str | None = None,
    response_format: str = 'text',
    threshold: float = 0.92,
) -> str:
    """Find near-duplicate memories using text similarity. Reports groups of memories with >92% similarity.

    Args:
        category: Filter to a specific category (optional)
        project_id:  (optional)
        response_format:  (one of: 'text', 'json') (optional)
        threshold: Similarity threshold 0.0-1.0 (optional)"""
    kwargs: dict = {}
    if category is not None:
        kwargs["category"] = category
    if project_id is not None:
        kwargs["project_id"] = project_id
    if response_format is not None:
        kwargs["response_format"] = response_format
    if threshold is not None:
        kwargs["threshold"] = threshold
    return call_tool("detect_duplicates", **kwargs)
