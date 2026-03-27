"""init_project — Initialize or update a scope entry in the memory manifest. The interface keeps the current project field name and creates the matching manifest entry plus default repo configurations."""

from __future__ import annotations

from code_execution.bridge import call_tool


def init_project(
    project: str,
    repos: list | str,
    *,
    description: str | None = None,
    set_repo_defaults: bool = False,
    tags: list | str | None = None,
) -> str:
    """Initialize or update a scope entry in the memory manifest. The interface keeps the current project field name and creates the matching manifest entry plus default repo configurations.

    Args:
        project: 
        repos: Repo names to associate with this project
        description:  (optional)
        set_repo_defaults:  (optional)
        tags:  (optional)"""
    kwargs: dict = {}
    kwargs["project"] = project
    kwargs["repos"] = repos
    if description is not None:
        kwargs["description"] = description
    if set_repo_defaults is not None:
        kwargs["set_repo_defaults"] = set_repo_defaults
    if tags is not None:
        kwargs["tags"] = tags
    return call_tool("init_project", **kwargs)
