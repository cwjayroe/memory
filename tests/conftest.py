from __future__ import annotations

import importlib
import sys
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT.parent
MODULES_TO_RESET = (
    "memory.chunking",
    "memory.constants",
    "memory.memory_types",
    "memory.formatting",
    "memory.helpers",
    "memory.ingest",
    "memory.manifest",
    "memory.mcp_server",
    "memory.memory_manager",
    "memory.scoring",
    "memory.server_config",
)


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


def _load_module(module_name: str) -> types.ModuleType:
    _install_fake_dependencies()
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))
    for package_module in MODULES_TO_RESET:
        sys.modules.pop(package_module, None)
    return importlib.import_module(f"memory.{module_name}")


def load_mcp_server_module():
    return _load_module("mcp_server")


@pytest.fixture
def mcp_module():
    return load_mcp_server_module()


def load_ingest_module():
    return _load_module("ingest")


def load_chunking_module():
    return _load_module("chunking")


@pytest.fixture
def ingest_module():
    return load_ingest_module()


@pytest.fixture
def chunking_module(ingest_module):
    """Return the chunking module loaded as a dependency of ingest_module.

    Must depend on ingest_module so both share the same module object — allowing
    monkeypatches (e.g. PdfReader) to affect the module that chunk_pdf_document
    actually references at runtime.
    """
    return sys.modules["memory.chunking"]


@pytest.fixture
def scoring_module():
    return _load_module("scoring")


@pytest.fixture
def memory_manager_module():
    return _load_module("memory_manager")


@pytest.fixture
def helpers_module():
    return _load_module("helpers")


@pytest.fixture
def manifest_module():
    return _load_module("manifest")


@pytest.fixture
def contracts_module():
    return _load_module("memory_types")


@pytest.fixture
def dataclasses_module():
    return _load_module("memory_types")


@pytest.fixture
def server_config_module():
    return _load_module("server_config")
