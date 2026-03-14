"""Tests for the cache_backend module."""

import time
import pytest
from cache_backend import InProcessCache, CacheBackend, create_cache_backend


class TestInProcessCache:
    def test_get_miss_returns_none(self):
        cache = InProcessCache()
        assert cache.get("missing") is None

    def test_set_and_get(self):
        cache = InProcessCache()
        cache.set("key1", "payload1", 60)
        assert cache.get("key1") == "payload1"

    def test_ttl_expiration(self):
        cache = InProcessCache(default_ttl=0.1)
        cache.set("key1", "payload1")
        assert cache.get("key1") == "payload1"
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_explicit_ttl_overrides_default(self):
        cache = InProcessCache(default_ttl=60)
        cache.set("key1", "payload1", 0.1)
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_max_entries_eviction(self):
        cache = InProcessCache(max_entries=2)
        cache.set("a", "1", 60)
        cache.set("b", "2", 60)
        cache.set("c", "3", 60)  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"

    def test_delete(self):
        cache = InProcessCache()
        cache.set("key1", "payload1", 60)
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_clear(self):
        cache = InProcessCache()
        cache.set("a", "1", 60)
        cache.set("b", "2", 60)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_stats_tracking(self):
        cache = InProcessCache(max_entries=2)
        cache.set("a", "1", 60)
        cache.get("a")  # hit
        cache.get("b")  # miss
        cache.set("b", "2", 60)
        cache.set("c", "3", 60)  # evicts "a"

        stats = cache.stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.sets == 3
        assert stats.evictions == 1

    def test_lru_ordering(self):
        cache = InProcessCache(max_entries=2)
        cache.set("a", "1", 60)
        cache.set("b", "2", 60)
        cache.get("a")  # access "a" to make it recently used
        cache.set("c", "3", 60)  # should evict "b"
        assert cache.get("a") == "1"
        assert cache.get("b") is None
        assert cache.get("c") == "3"


class TestCreateCacheBackend:
    def test_default_creates_in_process(self):
        backend = create_cache_backend()
        assert isinstance(backend, InProcessCache)

    def test_memory_backend(self):
        backend = create_cache_backend("memory", max_entries=64, default_ttl=30)
        assert isinstance(backend, InProcessCache)

    def test_redis_backend_graceful_failure(self):
        # Redis backend should handle connection failure gracefully
        backend = create_cache_backend(
            "redis",
            redis_url="redis://nonexistent-host:9999/0",
        )
        # Should not crash, just return cache misses
        assert backend.get("test") is None

    def test_backend_implements_interface(self):
        backend = create_cache_backend()
        assert isinstance(backend, CacheBackend)
        assert hasattr(backend, "get")
        assert hasattr(backend, "set")
        assert hasattr(backend, "delete")
        assert hasattr(backend, "clear")
        assert hasattr(backend, "stats")
