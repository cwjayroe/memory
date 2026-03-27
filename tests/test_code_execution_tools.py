"""Tests for the code execution MCP tool handlers."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import mcp_server


def _run(coro):
    """Run an async coroutine synchronously for tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestListCodeTools:
    def test_names_detail(self):
        results = _run(mcp_server._handle_list_code_tools({"detail": "names"}))
        text = results[0].text
        assert "Available memory tools" in text

    def test_summary_detail(self):
        results = _run(mcp_server._handle_list_code_tools({"detail": "summary"}))
        text = results[0].text
        assert "Available memory tools" in text
        # Should contain at least some known tool names
        assert "search_context" in text

    def test_full_detail(self):
        results = _run(mcp_server._handle_list_code_tools({"detail": "full"}))
        text = results[0].text
        assert "def search_context(" in text

    def test_default_detail(self):
        results = _run(mcp_server._handle_list_code_tools({}))
        text = results[0].text
        assert "Available memory tools" in text


class TestGetToolSource:
    def test_valid_tool(self):
        results = _run(mcp_server._handle_get_tool_source({"tool_name": "search_context"}))
        text = results[0].text
        assert "def search_context(" in text
        assert "call_tool" in text

    def test_invalid_tool(self):
        results = _run(mcp_server._handle_get_tool_source({"tool_name": "nonexistent_tool_xyz"}))
        text = results[0].text
        assert "not found" in text.lower()

    def test_invalid_characters(self):
        results = _run(mcp_server._handle_get_tool_source({"tool_name": "../../../etc/passwd"}))
        text = results[0].text
        assert "Invalid tool name" in text

    def test_store_memory_source(self):
        results = _run(mcp_server._handle_get_tool_source({"tool_name": "store_memory"}))
        text = results[0].text
        assert "def store_memory(" in text


class TestExecuteCode:
    def test_simple_print(self):
        results = _run(mcp_server._handle_execute_code({"code": 'print("hello from sandbox")'}))
        text = results[0].text
        assert "hello from sandbox" in text

    def test_empty_code(self):
        results = _run(mcp_server._handle_execute_code({"code": ""}))
        text = results[0].text
        assert "No code provided" in text

    def test_result_variable(self):
        results = _run(mcp_server._handle_execute_code({"code": '__result__ = "computed"'}))
        text = results[0].text
        assert "computed" in text

    def test_error_handling(self):
        results = _run(mcp_server._handle_execute_code({"code": '1/0'}))
        text = results[0].text
        assert "error" in text.lower()

    def test_timeout_parameter(self):
        results = _run(mcp_server._handle_execute_code({
            "code": 'while True: pass',
            "timeout": 2,
        }))
        text = results[0].text
        assert "timed out" in text.lower() or "timeout" in text.lower()


class TestToolDefinitionsRegistered:
    """Verify the new tools are in list_tools."""

    def test_execute_code_in_tools(self):
        tools = _run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert "execute_code" in names

    def test_list_code_tools_in_tools(self):
        tools = _run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert "list_code_tools" in names

    def test_get_tool_source_in_tools(self):
        tools = _run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert "get_tool_source" in names

    def test_execute_code_requires_code(self):
        tools = _run(mcp_server.list_tools())
        exec_tool = next(t for t in tools if t.name == "execute_code")
        assert "code" in exec_tool.inputSchema.get("required", [])

    def test_get_tool_source_requires_tool_name(self):
        tools = _run(mcp_server.list_tools())
        tool = next(t for t in tools if t.name == "get_tool_source")
        assert "tool_name" in tool.inputSchema.get("required", [])


class TestDispatcher:
    """Verify the dispatcher routes to the new handlers."""

    def test_execute_code_dispatch(self):
        results = _run(mcp_server.call_tool("execute_code", {"code": 'print("dispatch test")'}))
        text = results[0].text
        assert "dispatch test" in text

    def test_list_code_tools_dispatch(self):
        results = _run(mcp_server.call_tool("list_code_tools", {}))
        text = results[0].text
        assert "Available memory tools" in text

    def test_get_tool_source_dispatch(self):
        results = _run(mcp_server.call_tool("get_tool_source", {"tool_name": "search_context"}))
        text = results[0].text
        assert "def search_context(" in text
