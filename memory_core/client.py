"""MemoryClient — importable Python API for the memory backend.

Wraps mem0 directly so external consumers can ``pip install`` this package
and call ``MemoryClient`` without standing up the MCP server.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .config import MemoryConfig
from .models import MemoryEntry, SearchResult


class MemoryClient:
    """Simple four-method interface to the mem0 / ChromaDB memory backend.

    Usage::

        from memory_core import MemoryClient

        client = MemoryClient(agent_id="my-project")
        client.store("Implemented auth refresh token rotation")
        results = client.search("auth tokens")
    """

    def __init__(
        self,
        agent_id: str | None = None,
        config: MemoryConfig | None = None,
    ) -> None:
        self._config = config or MemoryConfig()
        self._agent_id = agent_id or self._config.default_agent_id
        self._memory: Any = None  # lazy-initialised

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_memory(self) -> Any:
        if self._memory is None:
            from mem0 import Memory  # type: ignore

            mem0_config = {
                "llm": {
                    "provider": "ollama",
                    "config": {
                        "model": self._config.ollama_model,
                        "ollama_base_url": self._config.ollama_host,
                    },
                },
                "embedder": {
                    "provider": "huggingface",
                    "config": {"model": self._config.embedding_model},
                },
                "vector_store": {
                    "provider": "chroma",
                    "config": {
                        "collection_name": f"project-memory-{self._agent_id}",
                        "path": os.path.join(
                            os.path.expanduser(self._config.chroma_path),
                            self._agent_id,
                            "chroma",
                        ),
                    },
                },
            }
            self._memory = Memory.from_config(mem0_config)
        return self._memory

    @staticmethod
    def _extract_results(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            data = raw.get("results")
            if isinstance(data, list):
                return data
        return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search memory for relevant entries.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.
            filters: Optional metadata key/value pairs to filter by.

        Returns:
            List of :class:`SearchResult` ordered by relevance score.
        """
        memory = self._get_memory()
        raw = memory.search(query=query, agent_id=self._agent_id, limit=limit)
        results: list[SearchResult] = []
        for item in self._extract_results(raw):
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if filters:
                if not all(meta.get(k) == v for k, v in filters.items()):
                    continue
            results.append(
                SearchResult(
                    id=str(item.get("id", "")),
                    content=str(item.get("memory", "")),
                    score=float(item.get("score", 0.0)),
                    metadata=meta,
                )
            )
        return results

    def store(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a new memory.

        Args:
            content: The text to store.
            metadata: Optional metadata dict; persisted and filterable.

        Returns:
            :class:`MemoryEntry` representing the stored memory.
        """
        memory = self._get_memory()
        meta = metadata or {}
        raw = memory.add(content, agent_id=self._agent_id, metadata=meta, infer=False)
        items = self._extract_results(raw)
        memory_id = str(items[0].get("id", "")) if items else ""
        return MemoryEntry(
            id=memory_id,
            content=content,
            metadata=meta,
            created_at=datetime.now(timezone.utc),
        )

    def list(
        self,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """List all memories, optionally filtered by metadata.

        Args:
            filters: Optional metadata key/value pairs; only matching
                entries are returned.

        Returns:
            List of :class:`MemoryEntry`.
        """
        memory = self._get_memory()
        raw = memory.get_all(agent_id=self._agent_id)
        entries: list[MemoryEntry] = []
        for item in self._extract_results(raw):
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if filters:
                if not all(meta.get(k) == v for k, v in filters.items()):
                    continue
            entries.append(
                MemoryEntry(
                    id=str(item.get("id", "")),
                    content=str(item.get("memory", "")),
                    metadata=meta,
                )
            )
        return entries

    def delete(self, memory_id: str) -> None:
        """Delete a memory by ID.

        Args:
            memory_id: The ID of the memory to delete.
        """
        memory = self._get_memory()
        memory.delete(memory_id)
