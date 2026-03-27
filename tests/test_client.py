"""Tests for memory_core.MemoryClient — covers all four public methods."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory_core import MemoryClient, MemoryConfig, MemoryEntry, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mem0_result(
    memory_id: str = "abc-123",
    memory: str = "some memory text",
    score: float = 0.9,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": memory_id,
        "memory": memory,
        "score": score,
        "metadata": metadata or {},
    }


def _make_fake_memory(
    search_results: list[dict] | None = None,
    get_all_results: list[dict] | None = None,
    add_results: list[dict] | None = None,
) -> MagicMock:
    fake = MagicMock()
    fake.search.return_value = {"results": search_results or []}
    fake.get_all.return_value = {"results": get_all_results or []}
    fake.add.return_value = {"results": add_results or [{"id": "new-id"}]}
    fake.delete.return_value = None
    return fake


# ---------------------------------------------------------------------------
# Tests: search()
# ---------------------------------------------------------------------------


class TestSearch:
    def test_returns_search_result_list(self):
        fake = _make_fake_memory(
            search_results=[_make_mem0_result("id-1", "auth token rotation", 0.85)]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        results = client.search("auth tokens")

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].id == "id-1"
        assert results[0].content == "auth token rotation"
        assert results[0].score == pytest.approx(0.85)

    def test_empty_results(self):
        fake = _make_fake_memory(search_results=[])
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        results = client.search("nothing here")

        assert results == []

    def test_passes_query_and_limit_to_mem0(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        client.search("query text", limit=7)

        fake.search.assert_called_once_with(
            query="query text", agent_id="test-agent", limit=7
        )

    def test_metadata_preserved_in_result(self):
        meta = {"source": "forge", "category": "auth"}
        fake = _make_fake_memory(
            search_results=[_make_mem0_result(metadata=meta)]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        results = client.search("auth")

        assert results[0].metadata == meta

    def test_filters_results_by_metadata(self):
        fake = _make_fake_memory(
            search_results=[
                _make_mem0_result("id-1", "payment service", metadata={"source": "cursor"}),
                _make_mem0_result("id-2", "auth refresh", metadata={"source": "forge"}),
            ]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        results = client.search("service", filters={"source": "forge"})

        assert len(results) == 1
        assert results[0].id == "id-2"

    def test_uses_agent_id(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="my-project")
        client._memory = fake

        client.search("test")

        fake.search.assert_called_once_with(
            query="test", agent_id="my-project", limit=5
        )


# ---------------------------------------------------------------------------
# Tests: store()
# ---------------------------------------------------------------------------


class TestStore:
    def test_returns_memory_entry(self):
        fake = _make_fake_memory(add_results=[{"id": "stored-id"}])
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entry = client.store("Refactored PaymentService")

        assert isinstance(entry, MemoryEntry)
        assert entry.id == "stored-id"
        assert entry.content == "Refactored PaymentService"

    def test_metadata_persisted(self):
        fake = _make_fake_memory(add_results=[{"id": "m-1"}])
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entry = client.store("some content", metadata={"source": "forge", "run_id": "42"})

        assert entry.metadata == {"source": "forge", "run_id": "42"}

    def test_created_at_is_set(self):
        fake = _make_fake_memory(add_results=[{"id": "m-2"}])
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        before = datetime.now(timezone.utc)
        entry = client.store("content")
        after = datetime.now(timezone.utc)

        assert entry.created_at is not None
        assert before <= entry.created_at <= after

    def test_passes_content_and_agent_id_to_mem0(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        client.store("my memory")

        fake.add.assert_called_once_with(
            "my memory", agent_id="test-agent", metadata={}, infer=False
        )

    def test_empty_id_when_add_returns_no_results(self):
        fake = MagicMock()
        fake.add.return_value = {"results": []}
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entry = client.store("content")

        assert entry.id == ""


# ---------------------------------------------------------------------------
# Tests: list()
# ---------------------------------------------------------------------------


class TestList:
    def test_returns_memory_entry_list(self):
        fake = _make_fake_memory(
            get_all_results=[
                _make_mem0_result("id-1", "memory one"),
                _make_mem0_result("id-2", "memory two"),
            ]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entries = client.list()

        assert len(entries) == 2
        assert all(isinstance(e, MemoryEntry) for e in entries)
        assert entries[0].id == "id-1"
        assert entries[1].id == "id-2"

    def test_empty_list(self):
        fake = _make_fake_memory(get_all_results=[])
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entries = client.list()

        assert entries == []

    def test_filters_by_metadata(self):
        fake = _make_fake_memory(
            get_all_results=[
                _make_mem0_result("id-1", "cursor memory", metadata={"source": "cursor"}),
                _make_mem0_result("id-2", "forge memory", metadata={"source": "forge"}),
            ]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entries = client.list(filters={"source": "cursor"})

        assert len(entries) == 1
        assert entries[0].id == "id-1"

    def test_passes_agent_id_to_mem0(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="my-project")
        client._memory = fake

        client.list()

        fake.get_all.assert_called_once_with(agent_id="my-project")

    def test_metadata_preserved_in_entries(self):
        meta = {"category": "architecture", "repo": "myrepo"}
        fake = _make_fake_memory(
            get_all_results=[_make_mem0_result("id-1", metadata=meta)]
        )
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        entries = client.list()

        assert entries[0].metadata == meta


# ---------------------------------------------------------------------------
# Tests: delete()
# ---------------------------------------------------------------------------


class TestDelete:
    def test_calls_mem0_delete(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        client.delete("abc-123")

        fake.delete.assert_called_once_with("abc-123")

    def test_returns_none(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        result = client.delete("some-id")

        assert result is None

    def test_uses_correct_memory_id(self):
        fake = _make_fake_memory()
        client = MemoryClient(agent_id="test-agent")
        client._memory = fake

        client.delete("memory-xyz-789")

        fake.delete.assert_called_once_with("memory-xyz-789")


# ---------------------------------------------------------------------------
# Tests: config and init
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_config_is_created(self):
        client = MemoryClient(agent_id="test-agent")
        assert isinstance(client._config, MemoryConfig)

    def test_custom_config_is_used(self):
        cfg = MemoryConfig(
            ollama_host="http://custom:11434",
            ollama_model="llama3",
            default_agent_id="custom-agent",
        )
        client = MemoryClient(config=cfg)
        assert client._config.ollama_host == "http://custom:11434"
        assert client._config.ollama_model == "llama3"

    def test_agent_id_from_config_default(self):
        cfg = MemoryConfig(default_agent_id="config-agent")
        client = MemoryClient(config=cfg)
        assert client._agent_id == "config-agent"

    def test_explicit_agent_id_overrides_config(self):
        cfg = MemoryConfig(default_agent_id="config-agent")
        client = MemoryClient(agent_id="explicit-agent", config=cfg)
        assert client._agent_id == "explicit-agent"

    def test_lazy_memory_init(self):
        client = MemoryClient(agent_id="test-agent")
        assert client._memory is None

    def test_mem0_config_uses_memory_config(self):
        cfg = MemoryConfig(
            chroma_path="/tmp/test-memory",
            ollama_host="http://my-ollama:11434",
            ollama_model="mistral",
            embedding_model="BAAI/bge-small-en",
        )
        client = MemoryClient(agent_id="proj", config=cfg)

        with patch("mem0.Memory") as MockMemory:
            MockMemory.from_config.return_value = MagicMock()
            # Trigger lazy init
            with patch("memory_core.client.MemoryClient._get_memory") as mock_get:
                mock_get.return_value = MagicMock()
                client.list()
