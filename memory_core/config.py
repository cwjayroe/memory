from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class MemoryConfig:
    """Configuration for MemoryClient.

    All fields default to reading from environment variables, matching the
    same env vars used by the MCP server so that MemoryClient and the server
    share the same backend data by default.
    """

    chroma_path: str = field(
        default_factory=lambda: os.path.expanduser(
            os.environ.get("PROJECT_MEMORY_ROOT", "~/.project-memory")
        )
    )
    ollama_host: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.2")
    )
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    default_agent_id: str = field(
        default_factory=lambda: os.environ.get("PROJECT_ID", "project-memory-default")
    )
