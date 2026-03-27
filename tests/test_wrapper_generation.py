"""Tests for the code execution wrapper generator."""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from code_execution.generate import generate_wrappers, _extract_params, _generate_wrapper_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockTool:
    def __init__(self, name: str, description: str, inputSchema: dict):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


SAMPLE_TOOLS = [
    _MockTool(
        name="search_context",
        description="Search scoped memory for context.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project_id": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
                "tags": {"type": ["array", "string"], "items": {"type": "string"}},
                "debug": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    ),
    _MockTool(
        name="store_memory",
        description="Store structured memory.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "project_id": {"type": "string"},
                "category": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["high", "normal", "low"],
                    "default": "normal",
                },
            },
            "required": ["content"],
        },
    ),
    _MockTool(
        name="delete_memory",
        description="Delete a memory by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "project_id": {"type": "string"},
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# _extract_params
# ---------------------------------------------------------------------------


class TestExtractParams:
    def test_required_params_come_first(self):
        params = _extract_params(SAMPLE_TOOLS[0].inputSchema)
        names = [p["name"] for p in params]
        assert names[0] == "query"
        assert all(not p["required"] for p in params[1:])

    def test_required_flag(self):
        params = _extract_params(SAMPLE_TOOLS[0].inputSchema)
        by_name = {p["name"]: p for p in params}
        assert by_name["query"]["required"] is True
        assert by_name["project_id"]["required"] is False

    def test_default_values(self):
        params = _extract_params(SAMPLE_TOOLS[0].inputSchema)
        by_name = {p["name"]: p for p in params}
        assert by_name["limit"]["default"] == 8
        assert by_name["debug"]["default"] is False

    def test_union_type(self):
        params = _extract_params(SAMPLE_TOOLS[0].inputSchema)
        by_name = {p["name"]: p for p in params}
        assert "list" in by_name["tags"]["type_hint"]
        assert "str" in by_name["tags"]["type_hint"]

    def test_enum_in_description(self):
        params = _extract_params(SAMPLE_TOOLS[1].inputSchema)
        by_name = {p["name"]: p for p in params}
        assert "high" in by_name["priority"]["description"]

    def test_no_required_means_all_optional(self):
        params = _extract_params(SAMPLE_TOOLS[2].inputSchema)
        assert all(not p["required"] for p in params)


# ---------------------------------------------------------------------------
# _generate_wrapper_source
# ---------------------------------------------------------------------------


class TestGenerateWrapperSource:
    def test_produces_valid_python(self):
        source = _generate_wrapper_source(
            "search_context",
            "Search memory.",
            SAMPLE_TOOLS[0].inputSchema,
        )
        # Should compile without errors
        ast.parse(source)

    def test_contains_function_def(self):
        source = _generate_wrapper_source(
            "store_memory",
            "Store memory.",
            SAMPLE_TOOLS[1].inputSchema,
        )
        assert "def store_memory(" in source

    def test_contains_docstring(self):
        source = _generate_wrapper_source(
            "search_context",
            "Search scoped memory for context.",
            SAMPLE_TOOLS[0].inputSchema,
        )
        assert "Search scoped memory for context." in source

    def test_imports_call_tool(self):
        source = _generate_wrapper_source(
            "search_context",
            "Search.",
            SAMPLE_TOOLS[0].inputSchema,
        )
        assert "from code_execution.bridge import call_tool" in source

    def test_calls_call_tool_with_name(self):
        source = _generate_wrapper_source(
            "search_context",
            "Search.",
            SAMPLE_TOOLS[0].inputSchema,
        )
        assert 'call_tool("search_context"' in source


# ---------------------------------------------------------------------------
# generate_wrappers (end-to-end)
# ---------------------------------------------------------------------------


class TestGenerateWrappers:
    def test_generates_one_file_per_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = generate_wrappers(SAMPLE_TOOLS, tmpdir)
            assert len(generated) == 3
            assert "search_context.py" in generated
            assert "store_memory.py" in generated
            assert "delete_memory.py" in generated

    def test_generated_files_are_valid_python(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_wrappers(SAMPLE_TOOLS, tmpdir)
            for py_file in Path(tmpdir).glob("*.py"):
                source = py_file.read_text(encoding="utf-8")
                ast.parse(source)  # Should not raise

    def test_init_reexports_all_functions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_wrappers(SAMPLE_TOOLS, tmpdir)
            init_content = (Path(tmpdir) / "__init__.py").read_text(encoding="utf-8")
            assert "from .search_context import search_context" in init_content
            assert "from .store_memory import store_memory" in init_content
            assert "from .delete_memory import delete_memory" in init_content

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_wrappers(SAMPLE_TOOLS, tmpdir)
            first_content = {
                f.name: f.read_text() for f in Path(tmpdir).glob("*.py")
            }
            generate_wrappers(SAMPLE_TOOLS, tmpdir)
            second_content = {
                f.name: f.read_text() for f in Path(tmpdir).glob("*.py")
            }
            assert first_content == second_content

    def test_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c"
            generate_wrappers(SAMPLE_TOOLS, nested)
            assert nested.exists()
            assert (nested / "search_context.py").exists()
