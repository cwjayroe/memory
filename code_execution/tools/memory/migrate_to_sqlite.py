"""migrate_to_sqlite — Migrate existing ChromaDB data to SQLite metadata store. Safe to run multiple times."""

from __future__ import annotations

from code_execution.bridge import call_tool


def migrate_to_sqlite(
    project_id: str | None = None,
) -> str:
    """Migrate existing ChromaDB data to SQLite metadata store. Safe to run multiple times.

    Args:
        project_id:  (optional)"""
    kwargs: dict = {}
    if project_id is not None:
        kwargs["project_id"] = project_id
    return call_tool("migrate_to_sqlite", **kwargs)
