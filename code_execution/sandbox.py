"""Subprocess-based sandbox executor for user-submitted Python code.

Launches ``runner.py`` in a subprocess with:
* Pipe-based IPC (inherited pipe fds, passed via ``_MCP_FD_OUT`` / ``_MCP_FD_IN``) for tool calls back to the parent.
* Timeout enforcement.
* Output capture and truncation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 100_000

# Path to runner.py (same directory as this file)
_RUNNER_PATH = str(Path(__file__).parent / "runner.py")
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)


async def _handle_tool_ipc(
    proc: subprocess.Popen,
    pipe_read_fd: int,
    pipe_write_fd: int,
) -> None:
    """Read tool-call requests from the subprocess and respond with results.

    The subprocess writes JSON requests on ``pipe_read_fd`` and reads
    JSON responses on ``pipe_write_fd``.
    """
    loop = asyncio.get_event_loop()
    reader_file = os.fdopen(pipe_read_fd, "r", buffering=1)
    writer_file = os.fdopen(pipe_write_fd, "w", buffering=1)

    try:
        while proc.poll() is None:
            # Non-blocking read with a short timeout
            line = await loop.run_in_executor(None, reader_file.readline)
            if not line:
                break

            try:
                request = json.loads(line)
                tool_name = request["tool"]
                tool_args = request.get("args", {})
            except (json.JSONDecodeError, KeyError) as exc:
                response = {"error": f"Invalid tool request: {exc}"}
                writer_file.write(json.dumps(response) + "\n")
                writer_file.flush()
                continue

            # Execute the tool via the MCP server handler
            try:
                from mcp_server import call_tool as _mcp_call_tool

                results = await _mcp_call_tool(tool_name, tool_args)
                text = "\n".join(r.text for r in results)
                response = {"result": text}
            except Exception as exc:
                response = {"error": str(exc)}

            writer_file.write(json.dumps(response) + "\n")
            writer_file.flush()
    except (OSError, BrokenPipeError):
        pass
    finally:
        try:
            reader_file.close()
        except OSError:
            pass
        try:
            writer_file.close()
        except OSError:
            pass


async def execute_code(
    code: str,
    timeout: int = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute Python code in a sandboxed subprocess.

    Parameters
    ----------
    code:
        Python source code to execute.
    timeout:
        Maximum execution time in seconds.

    Returns
    -------
    Dict with keys: stdout, stderr, return_value, error.
    """
    # Write code to a temp file
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix="mcp_sandbox_",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(code)
        tmp.close()

        # Create pipes for tool-call IPC.  ``pass_fds`` keeps the same numeric fds in the
        # child as in the parent — they are rarely 3 and 4, so expose the real numbers via env.
        parent_r, child_w = os.pipe()
        child_r, parent_w = os.pipe()

        env = os.environ.copy()
        env["_MCP_SANDBOX"] = "1"
        env["_MCP_FD_OUT"] = str(child_w)
        env["_MCP_FD_IN"] = str(child_r)

        # Launch subprocess
        proc = subprocess.Popen(
            [sys.executable, _RUNNER_PATH, tmp.name, _REPO_ROOT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
            pass_fds=(child_w, child_r),
            cwd=tempfile.gettempdir(),
        )

        # Close the child ends in the parent
        os.close(child_w)
        os.close(child_r)

        # Handle tool IPC in background
        ipc_task = asyncio.create_task(
            _handle_tool_ipc(proc, parent_r, parent_w)
        )

        # Wait for completion with timeout
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, proc.communicate
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            proc.wait()
            ipc_task.cancel()
            return {
                "stdout": "",
                "stderr": "",
                "return_value": None,
                "error": f"Execution timed out after {timeout} seconds",
            }

        ipc_task.cancel()
        try:
            await ipc_task
        except asyncio.CancelledError:
            pass

        # Parse output
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # Truncate if needed
        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [output truncated]"
        if len(stderr) > MAX_OUTPUT_BYTES:
            stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... [output truncated]"

        # The runner prints a JSON envelope as the last line of stdout
        result: dict[str, Any] = {
            "stdout": "",
            "stderr": stderr,
            "return_value": None,
            "error": None,
        }

        if proc.returncode != 0 and not stdout.strip():
            result["error"] = f"Process exited with code {proc.returncode}"
            result["stderr"] = stderr
            return result

        # Extract the JSON envelope from stdout
        try:
            envelope = json.loads(stdout.strip().rsplit("\n", 1)[-1])
            result["stdout"] = envelope.get("stdout", "")
            result["return_value"] = envelope.get("return_value")
            result["error"] = envelope.get("error")
        except (json.JSONDecodeError, IndexError):
            # If we can't parse the envelope, treat all stdout as output
            result["stdout"] = stdout

        return result

    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
