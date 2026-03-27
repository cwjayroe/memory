"""summarize_scope — Generate a prose summary of what a scope contains, grouped by category, using the configured LLM."""

from __future__ import annotations

from code_execution.bridge import call_tool


def summarize_scope(
    category: str | None = None,
    max_tokens: int = 800,
    project_id: str | None = None,
    repo: str | None = None,
) -> str:
    """Generate a prose summary of what a scope contains, grouped by category, using the configured LLM.

    Args:
        category: Filter summary to a specific category (optional)
        max_tokens:  (optional)
        project_id:  (optional)
        repo: Filter summary to a specific repo (optional)"""
    kwargs: dict = {}
    if category is not None:
        kwargs["category"] = category
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if project_id is not None:
        kwargs["project_id"] = project_id
    if repo is not None:
        kwargs["repo"] = repo
    return call_tool("summarize_scope", **kwargs)
