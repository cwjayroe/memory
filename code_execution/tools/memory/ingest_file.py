"""ingest_file — Ingest a single file into scoped memory, replacing any existing chunks for that file. The project field selects the target scope."""

from __future__ import annotations

from code_execution.bridge import call_tool


def ingest_file(
    path: str,
    project: str,
    repo: str,
    *,
    mode: str = 'mixed',
    tags: list | str | None = None,
) -> str:
    """Ingest a single file into scoped memory, replacing any existing chunks for that file. The project field selects the target scope.

    Args:
        path: Absolute or home-relative path to the file
        project: 
        repo: 
        mode: Chunking mode: docstrings, headings, code-chunks, or mixed (optional)
        tags:  (optional)"""
    kwargs: dict = {}
    kwargs["path"] = path
    kwargs["project"] = project
    kwargs["repo"] = repo
    if mode is not None:
        kwargs["mode"] = mode
    if tags is not None:
        kwargs["tags"] = tags
    return call_tool("ingest_file", **kwargs)
