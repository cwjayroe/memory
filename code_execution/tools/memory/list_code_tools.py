"""list_code_tools — List available memory tool wrapper functions for use with execute_code. Returns function names, descriptions, and optionally full signatures. Use this for on-demand tool discovery instead of loading all tool definitions."""

from __future__ import annotations

from code_execution.bridge import call_tool


def list_code_tools(
    detail: str = 'summary',
) -> str:
    """List available memory tool wrapper functions for use with execute_code. Returns function names, descriptions, and optionally full signatures. Use this for on-demand tool discovery instead of loading all tool definitions.

    Args:
        detail: Level of detail: 'names' for function names only, 'summary' for name + description, 'full' for complete source code with signatures and docstrings (one of: 'names', 'summary', 'full') (optional)"""
    kwargs: dict = {}
    if detail is not None:
        kwargs["detail"] = detail
    return call_tool("list_code_tools", **kwargs)
