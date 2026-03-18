"""ingest_repo — Ingest all files in a repository into scoped memory. The project field selects the target scope. Existing chunks for each file are replaced."""

from __future__ import annotations

from code_execution.bridge import call_tool


def ingest_repo(
    project: str,
    repo: str,
    *,
    exclude: list | str | None = None,
    include: list | str | None = None,
    mode: str = 'mixed',
    root: str | None = None,
    tags: list | str | None = None,
) -> str:
    """Ingest all files in a repository into scoped memory. The project field selects the target scope. Existing chunks for each file are replaced.

    Args:
        project: 
        repo: 
        exclude: Glob patterns to exclude (overrides manifest defaults) (optional)
        include: Glob patterns to include (overrides manifest defaults) (optional)
        mode: Chunking mode: docstrings, headings, code-chunks, or mixed (optional)
        root: Override the repo root path (optional)
        tags:  (optional)"""
    kwargs: dict = {}
    kwargs["project"] = project
    kwargs["repo"] = repo
    if exclude is not None:
        kwargs["exclude"] = exclude
    if include is not None:
        kwargs["include"] = include
    if mode is not None:
        kwargs["mode"] = mode
    if root is not None:
        kwargs["root"] = root
    if tags is not None:
        kwargs["tags"] = tags
    return call_tool("ingest_repo", **kwargs)
