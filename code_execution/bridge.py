"""Bridge between generated tool wrappers and MCP server handlers.

Provides ``call_tool(name, **kwargs) -> str`` which routes to the real
``mcp_server.call_tool`` async handler.

Two modes:
* **In-process** (default) — calls the handler directly via ``asyncio``.
* **Subprocess IPC** — when ``_MCP_SANDBOX`` env-var is set, communicates
  with the parent over fds from ``_MCP_FD_OUT`` (write) and ``_MCP_FD_IN`` (read).
"""

from __future__ import annotations

import json
import os
from typing import Any


def _call_tool_in_process(name: str, kwargs: dict[str, Any]) -> str:
    """Invoke the MCP handler directly (same process as the server)."""
    import asyncio
    import concurrent.futures

    from mcp_server import call_tool as _mcp_call_tool

    async def _invoke() -> str:
        results = await _mcp_call_tool(name, kwargs)
        return "\n".join(r.text for r in results)

    try:
        asyncio.get_running_loop()
        # Already inside an event loop — run in a thread to avoid deadlock.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _invoke()).result()
    except RuntimeError:
        return asyncio.run(_invoke())


def _call_tool_subprocess(name: str, kwargs: dict[str, Any]) -> str:
    """Send a tool-call request to the parent process over fd-pipe IPC."""
    request = json.dumps({"tool": name, "args": kwargs}) + "\n"

    fd_out_s = os.environ.get("_MCP_FD_OUT")
    fd_in_s = os.environ.get("_MCP_FD_IN")
    if fd_out_s is None or fd_in_s is None:
        raise RuntimeError(
            "Subprocess tool IPC requires _MCP_FD_OUT and _MCP_FD_IN "
            "(set by code_execution.sandbox when spawning the runner)."
        )
    fd_out = int(fd_out_s)
    fd_in = int(fd_in_s)

    os.write(fd_out, request.encode())

    # Read response (newline-terminated JSON)
    buf = b""
    while True:
        chunk = os.read(fd_in, 4096)
        if not chunk:
            raise RuntimeError("Parent closed IPC pipe")
        buf += chunk
        if b"\n" in buf:
            break

    response = json.loads(buf.split(b"\n", 1)[0])
    if "error" in response:
        raise RuntimeError(f"Tool call failed: {response['error']}")
    return response.get("result", "")


def call_tool(name: str, **kwargs: Any) -> str:
    """Invoke an MCP tool by name and return the text result.

    Automatically selects in-process or subprocess IPC mode depending on
    whether the ``_MCP_SANDBOX`` environment variable is set.
    """
    if os.environ.get("_MCP_SANDBOX"):
        return _call_tool_subprocess(name, kwargs)
    return _call_tool_in_process(name, kwargs)
