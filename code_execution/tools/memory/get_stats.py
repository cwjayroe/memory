"""get_stats — Return aggregate statistics for a scope: total count, breakdown by category/repo/source_kind/priority, oldest/newest timestamps, estimated token coverage."""

from __future__ import annotations

from code_execution.bridge import call_tool


def get_stats(
    project_id: str | None = None,
    repo: str | None = None,
) -> str:
    """Return aggregate statistics for a scope: total count, breakdown by category/repo/source_kind/priority, oldest/newest timestamps, estimated token coverage.

    Args:
        project_id:  (optional)
        repo: Optional repo filter (optional)"""
    kwargs: dict = {}
    if project_id is not None:
        kwargs["project_id"] = project_id
    if repo is not None:
        kwargs["repo"] = repo
    return call_tool("get_stats", **kwargs)
