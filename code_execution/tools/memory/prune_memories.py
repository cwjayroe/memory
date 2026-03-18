"""prune_memories — Remove duplicate or stale memories from a selected scope. Prune by duplicate fingerprint, by missing source paths, or both."""

from __future__ import annotations

from code_execution.bridge import call_tool


def prune_memories(
    project: str,
    *,
    by: str = 'both',
    path_prefix: str | None = None,
    repo: str | None = None,
) -> str:
    """Remove duplicate or stale memories from a selected scope. Prune by duplicate fingerprint, by missing source paths, or both.

    Args:
        project: 
        by:  (one of: 'fingerprint', 'path', 'both') (optional)
        path_prefix:  (optional)
        repo:  (optional)"""
    kwargs: dict = {}
    kwargs["project"] = project
    if by is not None:
        kwargs["by"] = by
    if path_prefix is not None:
        kwargs["path_prefix"] = path_prefix
    if repo is not None:
        kwargs["repo"] = repo
    return call_tool("prune_memories", **kwargs)
