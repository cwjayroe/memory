"""policy_run — Run the retention policy for a selected scope in dry-run or apply mode."""

from __future__ import annotations

from code_execution.bridge import call_tool


def policy_run(
    project: str,
    *,
    mode: str = 'dry-run',
    path_prefix: str | None = None,
    repo: str | None = None,
    stale_days: int = 45,
    summary_keep: int = 5,
    verbose: bool = False,
) -> str:
    """Run the retention policy for a selected scope in dry-run or apply mode.

    Args:
        project: 
        mode:  (one of: 'dry-run', 'apply') (optional)
        path_prefix:  (optional)
        repo:  (optional)
        stale_days:  (optional)
        summary_keep:  (optional)
        verbose: In dry-run mode: show per-memory details (excerpt, reason, age) for each deletion candidate (optional)"""
    kwargs: dict = {}
    kwargs["project"] = project
    if mode is not None:
        kwargs["mode"] = mode
    if path_prefix is not None:
        kwargs["path_prefix"] = path_prefix
    if repo is not None:
        kwargs["repo"] = repo
    if stale_days is not None:
        kwargs["stale_days"] = stale_days
    if summary_keep is not None:
        kwargs["summary_keep"] = summary_keep
    if verbose is not None:
        kwargs["verbose"] = verbose
    return call_tool("policy_run", **kwargs)
