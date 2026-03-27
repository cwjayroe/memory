"""Subprocess entry-point for sandboxed code execution.

Launched by ``sandbox.py`` via ``subprocess.Popen``.  Sets up:
* ``sys.path`` so ``code_execution.tools.memory`` is importable.
* An import hook blocking dangerous modules.
* Resource limits (Linux only).
* Executes user code via ``exec()`` in a restricted globals dict.
* Captures ``__result__`` if set, prints JSON envelope on exit.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import sys
import traceback
from io import StringIO


# ---------------------------------------------------------------------------
# Forbidden-import hook
# ---------------------------------------------------------------------------

# ``os`` is allowed so ``code_execution.bridge`` can load in the sandbox; it uses
# ``os.environ`` and ``os.read`` / ``os.write`` on IPC fds for tool calls. User code
# can therefore import ``os`` as well (same tradeoff as other permissive sandboxes).
FORBIDDEN_MODULES = frozenset({
    "subprocess", "shutil", "signal", "socket",
    "ctypes", "pathlib", "glob", "tempfile",
    "webbrowser", "http", "urllib", "ftplib", "smtplib",
    "multiprocessing", "threading", "concurrent",
    "importlib", "runpy", "compileall",
    "pickle", "shelve", "marshal",
})


class _ForbiddenImportFinder(importlib.abc.MetaPathFinder):
    """Block imports of modules in the forbidden set."""

    def find_module(self, fullname: str, path=None):  # noqa: D102 — unused in modern Python
        return self.find_spec(fullname, path)

    def find_spec(self, fullname: str, path, target=None):
        top = fullname.split(".")[0]
        if top in FORBIDDEN_MODULES:
            raise ImportError(
                f"Import of '{fullname}' is not allowed in the sandbox"
            )
        return None  # Let the default finders handle it


# ---------------------------------------------------------------------------
# Resource limits (Linux)
# ---------------------------------------------------------------------------

def _apply_resource_limits(cpu_seconds: int = 30, mem_bytes: int = 256 * 1024 * 1024) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        # Prevent writing files
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass  # Non-Linux or restricted environment


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Execute user code passed as the first CLI argument (file path)."""
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: runner.py <code_file> <repo_root>"}))
        sys.exit(1)

    code_file = sys.argv[1]
    repo_root = sys.argv[2]

    # Set up sys.path so wrappers are importable
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Set sandbox env variable so the bridge uses IPC mode
    import os
    os.environ["_MCP_SANDBOX"] = "1"

    # Install forbidden-import hook
    sys.meta_path.insert(0, _ForbiddenImportFinder())

    # Remove forbidden modules from sys.modules so user code can't access them
    # via cached imports from the runner's own startup.
    for mod_name in list(sys.modules):
        top = mod_name.split(".")[0]
        if top in FORBIDDEN_MODULES:
            del sys.modules[mod_name]

    # Apply resource limits
    _apply_resource_limits()

    # Read the user code
    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    # Execute in a restricted globals dict
    captured_stdout = StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured_stdout

    user_globals: dict = {
        "__builtins__": __builtins__,
        "__name__": "__main__",
    }

    error_msg = None
    try:
        compiled = compile(code, "<sandbox>", "exec")
        exec(compiled, user_globals)  # noqa: S102
    except Exception:
        error_msg = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    # Build result envelope
    result_value = user_globals.get("__result__")
    if result_value is not None:
        try:
            result_value = str(result_value)
        except Exception:
            result_value = repr(result_value)

    envelope = {
        "stdout": captured_stdout.getvalue(),
        "return_value": result_value,
        "error": error_msg,
    }

    # Print to real stdout (which the parent reads as subprocess stdout)
    print(json.dumps(envelope))


if __name__ == "__main__":
    main()
