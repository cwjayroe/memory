from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

import memory_manager as memory_manager_module


def _manager():
    return memory_manager_module.MemoryManager(
        config=memory_manager_module.ServerConfig(),
        scoring_engine=memory_manager_module.ScoringEngine(),
        logger=logging.getLogger("memory_manager_test"),
    )


def test_get_memory_with_retry_recovers_transient_error(monkeypatch):
    manager = _manager()
    calls = {"count": 0}
    sentinel = object()

    def fake_get_memory_uncached(_project_id: str):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("RustBindingsAPI object has no attribute 'bindings'")
        return sentinel

    monkeypatch.setattr(manager, "_get_memory_uncached", fake_get_memory_uncached)
    monkeypatch.setattr(manager, "_clear_cache_entry", lambda _project_id: None)

    result = manager.get_memory(
        "automatic-discounts",
        retries=2,
        backoff_seconds=0.0,
    )
    assert result is sentinel
    assert calls["count"] == 2


def test_concurrent_get_memory_with_retry_initializes_once(monkeypatch):
    manager = _manager()
    manager._memory_cache.clear()
    init_counter = {"count": 0}
    counter_lock = threading.Lock()

    class _MemoryFactory:
        @classmethod
        def from_config(cls, _config):
            with counter_lock:
                init_counter["count"] += 1
            time.sleep(0.05)
            return object()

    monkeypatch.setattr(memory_manager_module, "Memory", _MemoryFactory)
    monkeypatch.setattr(memory_manager_module, "build_mem0_config", lambda _project_id: {"ok": True})

    def worker() -> object:
        return manager.get_memory("automatic-discounts", retries=0)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _idx: worker(), range(6)))

    assert init_counter["count"] == 1
    assert all(result is results[0] for result in results)


def test_search_project_sync_uses_retry_helper(monkeypatch):
    manager = _manager()
    calls: list[str] = []

    class _DummyMemory:
        def search(self, **_kwargs):
            return {"results": [{"id": "abc", "memory": "hit"}]}

    def fake_get_memory(project_id: str, **_kwargs):
        calls.append(project_id)
        return _DummyMemory()

    monkeypatch.setattr(manager, "get_memory", fake_get_memory)

    results = manager._search_project_sync("automatic-discounts", "discounts", 10)
    assert calls == ["automatic-discounts"]
    assert len(results) == 1


def test_store_list_delete_use_retry_helper(monkeypatch):
    manager = _manager()
    calls: list[str] = []

    class _DummyMemory:
        def __init__(self):
            self.deleted: list[str] = []

        def get_all(self, **_kwargs):
            return {"results": []}

        def add(self, _content, **_kwargs):
            return {"results": [{"id": "new-id"}]}

        def delete(self, memory_id: str):
            self.deleted.append(memory_id)

    memory = _DummyMemory()

    def fake_get_memory(project_id: str, **_kwargs):
        calls.append(project_id)
        return memory

    monkeypatch.setattr(manager, "get_memory", fake_get_memory)

    manager.list_memories(
        request=memory_manager_module.ListMemoriesRequest(
            project_id="customcheckout-practices",
            repo=None,
            category=None,
            tag=None,
            path_prefix=None,
            offset=0,
            limit=5,
            response_format="text",
            include_full_text=False,
            excerpt_chars=420,
        )
    )
    manager.store_memory(
        request=memory_manager_module.StoreMemoryRequest(
            project_id="customcheckout-practices",
            content="summary",
            repo=None,
            source_path=None,
            source_kind="summary",
            category="summary",
            module=None,
            tags=[],
            upsert_key=None,
            fingerprint=None,
        )
    )
    manager.delete_memory(
        request=memory_manager_module.DeleteMemoryRequest(
            project_id="customcheckout-practices",
            memory_id="new-id",
            upsert_key=None,
        )
    )

    assert calls == [
        "customcheckout-practices",
        "customcheckout-practices",
        "customcheckout-practices",
    ]
    assert memory.deleted == ["new-id"]
