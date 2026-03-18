"""context_plan — Preview the resolved layered context payloads for a repo using the configured manifest and context pack."""

from __future__ import annotations

from code_execution.bridge import call_tool


def context_plan(
    repo: str,
    *,
    pack: str = 'default_3_layer',
    project: str | None = None,
) -> str:
    """Preview the resolved layered context payloads for a repo using the configured manifest and context pack.

    Args:
        repo: 
        pack:  (optional)
        project:  (optional)"""
    kwargs: dict = {}
    kwargs["repo"] = repo
    if pack is not None:
        kwargs["pack"] = pack
    if project is not None:
        kwargs["project"] = project
    return call_tool("context_plan", **kwargs)
