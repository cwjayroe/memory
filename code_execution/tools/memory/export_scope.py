"""export_scope — Export all memories for a scope as a JSON array or newline-delimited JSON. Useful for backup or cross-machine migration."""

from __future__ import annotations

from code_execution.bridge import call_tool


def export_scope(
    format: str = 'json',
    project_id: str | None = None,
) -> str:
    """Export all memories for a scope as a JSON array or newline-delimited JSON. Useful for backup or cross-machine migration.

    Args:
        format:  (one of: 'json', 'ndjson') (optional)
        project_id:  (optional)"""
    kwargs: dict = {}
    if format is not None:
        kwargs["format"] = format
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("export_scope", **kwargs)
