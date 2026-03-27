"""Tests for the sandbox executor and runner."""

from __future__ import annotations

import asyncio
import json

import pytest

from code_execution.sandbox import execute_code


def _run(coro):
    """Run an async coroutine synchronously for tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSandboxBasicExecution:
    def test_print_hello(self):
        result = _run(execute_code('print("hello")'))
        assert result["stdout"].strip() == "hello"
        assert result["error"] is None

    def test_result_variable(self):
        result = _run(execute_code('__result__ = 42'))
        assert result["return_value"] == "42"
        assert result["error"] is None

    def test_expression_result(self):
        result = _run(execute_code('__result__ = 2 + 2'))
        assert result["return_value"] == "4"

    def test_multiline_code(self):
        code = """\
items = [1, 2, 3, 4, 5]
total = sum(items)
print(f"Total: {total}")
__result__ = total
"""
        result = _run(execute_code(code))
        assert "Total: 15" in result["stdout"]
        assert result["return_value"] == "15"

    def test_empty_code(self):
        result = _run(execute_code(''))
        # Should execute without error
        assert result["error"] is None


class TestSandboxErrors:
    def test_syntax_error(self):
        result = _run(execute_code('def foo('))
        assert result["error"] is not None
        assert "SyntaxError" in result["error"]

    def test_runtime_error(self):
        result = _run(execute_code('1 / 0'))
        assert result["error"] is not None
        assert "ZeroDivisionError" in result["error"]

    def test_name_error(self):
        result = _run(execute_code('print(undefined_variable)'))
        assert result["error"] is not None
        assert "NameError" in result["error"]


class TestSandboxSecurity:
    def test_allowed_import_os_for_memory_bridge(self):
        result = _run(execute_code('import os\n__result__ = os.name'))
        assert result["error"] is None
        assert result["return_value"]

    def test_memory_wrappers_import_in_sandbox(self):
        code = "from code_execution.tools.memory import get_stats\n__result__ = 'import_ok'"
        result = _run(execute_code(code))
        assert result["error"] is None
        assert result["return_value"] == "import_ok"

    def test_forbidden_import_subprocess(self):
        result = _run(execute_code('import subprocess'))
        assert result["error"] is not None

    def test_forbidden_import_shutil(self):
        result = _run(execute_code('import shutil'))
        assert result["error"] is not None

    def test_forbidden_from_import_subprocess(self):
        result = _run(execute_code('from subprocess import Popen'))
        assert result["error"] is not None

    def test_allowed_import_json(self):
        result = _run(execute_code('import json; print(json.dumps({"a": 1}))'))
        assert result["error"] is None
        assert '{"a": 1}' in result["stdout"]

    def test_allowed_import_math(self):
        result = _run(execute_code('import math; print(math.pi)'))
        assert result["error"] is None
        assert "3.14" in result["stdout"]


class TestSandboxTimeout:
    def test_timeout_kills_process(self):
        code = "while True: pass"
        result = _run(execute_code(code, timeout=2))
        assert result["error"] is not None
        assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()


class TestSandboxOutputTruncation:
    def test_large_output_truncated(self):
        code = 'print("x" * 200000)'
        result = _run(execute_code(code, timeout=10))
        # Output should either be truncated or complete but bounded
        assert result["error"] is None or "truncated" in str(result.get("stdout", ""))
