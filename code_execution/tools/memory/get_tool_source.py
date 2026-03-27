"""get_tool_source — Read the full source code of a specific memory tool wrapper function, including its typed signature and docstring."""

from __future__ import annotations

from code_execution.bridge import call_tool


def get_tool_source(
    tool_name: str,
) -> str:
    """Read the full source code of a specific memory tool wrapper function, including its typed signature and docstring.

    Args:
        tool_name: Name of the tool (e.g., 'search_context', 'store_memory')"""
    kwargs: dict = {}
    kwargs["tool_name"] = tool_name
    return call_tool("get_tool_source", **kwargs)
