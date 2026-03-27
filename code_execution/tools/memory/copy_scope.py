"""copy_scope — Copy all memories from one scope to another. Use dry_run=true to preview without writing."""

from __future__ import annotations

from code_execution.bridge import call_tool


def copy_scope(
    from_project_id: str,
    to_project_id: str,
    *,
    dry_run: bool = False,
) -> str:
    """Copy all memories from one scope to another. Use dry_run=true to preview without writing.

    Args:
        from_project_id: 
        to_project_id: 
        dry_run:  (optional)"""
    kwargs: dict = {}
    kwargs["from_project_id"] = from_project_id
    kwargs["to_project_id"] = to_project_id
    if dry_run is not None:
        kwargs["dry_run"] = dry_run
    return call_tool("copy_scope", **kwargs)
