from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest


class _FakeMemory:
    @classmethod
    def from_config(cls, _config):
        return cls()

    def search(self, **_kwargs):
        return {"results": []}

    def get_all(self, **_kwargs):
        return {"results": []}

    def add(self, _content, **_kwargs):
        return {"results": [{"id": "fake-id"}]}

    def delete(self, _memory_id):
        return None


class _FakeServer:
    def __init__(self, _name: str):
        self._tools = None
        self._call_tool = None

    def list_tools(self):
        def decorator(func):
            self._tools = func
            return func

        return decorator

    def call_tool(self):
        def decorator(func):
            self._call_tool = func
            return func

        return decorator

    async def run(self, *_args, **_kwargs):
        return None

    def create_initialization_options(self):
        return {}


@dataclass
class _FakeTextContent:
    type: str
    text: str


@dataclass
class _FakeTool:
    name: str
    description: str
    inputSchema: dict


def _install_fake_dependencies() -> None:
    mem0_module = types.ModuleType("mem0")
    mem0_module.Memory = _FakeMemory

    mcp_module = types.ModuleType("mcp")
    mcp_server_module = types.ModuleType("mcp.server")
    mcp_stdio_module = types.ModuleType("mcp.server.stdio")
    mcp_types_module = types.ModuleType("mcp.types")

    mcp_server_module.Server = _FakeServer

    @asynccontextmanager
    async def _stdio_server():
        yield (None, None)

    mcp_stdio_module.stdio_server = _stdio_server
    mcp_types_module.TextContent = _FakeTextContent
    mcp_types_module.Tool = _FakeTool

    sys.modules["mem0"] = mem0_module
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = mcp_server_module
    sys.modules["mcp.server.stdio"] = mcp_stdio_module
    sys.modules["mcp.types"] = mcp_types_module


_install_fake_dependencies()

import ingest
import mcp_server


@pytest.fixture(autouse=True)
def _reset_module_state():
    ingest._MEM_MANAGER = None
    mcp_server.mem_manager._search_cache.clear()
    mcp_server.mem_manager._memory_cache.clear()
    yield
    ingest._MEM_MANAGER = None
    mcp_server.mem_manager._search_cache.clear()
    mcp_server.mem_manager._memory_cache.clear()
