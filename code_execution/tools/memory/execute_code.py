"""execute_code — Execute Python code in a sandboxed environment with access to memory tool wrappers. Import tools from 'code_execution.tools.memory' (e.g., 'from code_execution.tools.memory import search_context, store_memory'). Intermediate results stay in the sandbox; only explicitly printed output or the __result__ variable value is returned. Use this to compose multiple tool calls, filter large result sets, or perform complex operations in one step."""

from __future__ import annotations

from code_execution.bridge import call_tool


def execute_code(
    code: str,
    *,
    timeout: int = 30,
) -> str:
    """Execute Python code in a sandboxed environment with access to memory tool wrappers. Import tools from 'code_execution.tools.memory' (e.g., 'from code_execution.tools.memory import search_context, store_memory'). Intermediate results stay in the sandbox; only explicitly printed output or the __result__ variable value is returned. Use this to compose multiple tool calls, filter large result sets, or perform complex operations in one step.

    Args:
        code: Python code to execute. Use print() for output or assign to __result__.
        timeout: Max execution time in seconds (1-60) (optional)"""
    kwargs: dict = {}
    kwargs["code"] = code
    if timeout is not None:
        kwargs["timeout"] = timeout
    return call_tool("execute_code", **kwargs)
