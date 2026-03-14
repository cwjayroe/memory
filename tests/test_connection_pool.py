"""Tests for the ConnectionPool module."""

import threading
import time
import pytest
from connection_pool import ConnectionPool, PoolStats


def _factory(key: str) -> str:
    """Simple factory that returns the key itself."""
    return f"instance-{key}"


class TestConnectionPoolBasic:
    def test_get_creates_new_entry(self):
        pool = ConnectionPool(_factory, max_size=10)
        value = pool.get("alpha")
        assert value == "instance-alpha"
        assert len(pool) == 1

    def test_get_returns_cached_entry(self):
        calls = []
        def counting_factory(key):
            calls.append(key)
            return f"v-{key}"

        pool = ConnectionPool(counting_factory, max_size=10)
        v1 = pool.get("x")
        v2 = pool.get("x")
        assert v1 == v2
        assert len(calls) == 1  # factory called only once

    def test_stats_tracks_hits_and_misses(self):
        pool = ConnectionPool(_factory, max_size=10)
        pool.get("a")  # miss
        pool.get("a")  # hit
        pool.get("b")  # miss
        stats = pool.stats
        assert stats.misses == 2
        assert stats.hits == 1
        assert stats.current_size == 2

    def test_contains(self):
        pool = ConnectionPool(_factory, max_size=10)
        assert "z" not in pool
        pool.get("z")
        assert "z" in pool

    def test_keys(self):
        pool = ConnectionPool(_factory, max_size=10)
        pool.get("a")
        pool.get("b")
        assert set(pool.keys()) == {"a", "b"}


class TestConnectionPoolEviction:
    def test_lru_eviction_when_max_size_exceeded(self):
        evicted = []
        pool = ConnectionPool(
            _factory,
            max_size=2,
            on_evict=lambda k, v: evicted.append(k),
        )
        pool.get("a")
        pool.get("b")
        pool.get("c")  # should evict "a"
        assert len(pool) == 2
        assert "a" in evicted
        assert "b" in pool
        assert "c" in pool

    def test_access_refreshes_lru_order(self):
        evicted = []
        pool = ConnectionPool(
            _factory,
            max_size=2,
            on_evict=lambda k, v: evicted.append(k),
        )
        pool.get("a")
        pool.get("b")
        pool.get("a")  # refresh "a"
        pool.get("c")  # should evict "b" (least recently used)
        assert "b" in evicted
        assert "a" in pool

    def test_remove_explicit(self):
        pool = ConnectionPool(_factory, max_size=10)
        pool.get("x")
        assert "x" in pool
        pool.remove("x")
        assert "x" not in pool

    def test_clear_removes_all(self):
        pool = ConnectionPool(_factory, max_size=10)
        pool.get("a")
        pool.get("b")
        pool.clear()
        assert len(pool) == 0


class TestConnectionPoolTTL:
    def test_expired_entry_is_recreated(self):
        calls = []
        def counting_factory(key):
            calls.append(key)
            return f"v-{len(calls)}"

        pool = ConnectionPool(counting_factory, max_size=10, ttl_seconds=0.1)
        v1 = pool.get("a")
        time.sleep(0.15)
        v2 = pool.get("a")
        assert v1 != v2  # recreated after expiration
        assert len(calls) == 2

    def test_purge_expired(self):
        pool = ConnectionPool(_factory, max_size=10, ttl_seconds=0.1)
        pool.get("a")
        pool.get("b")
        time.sleep(0.15)
        purged = pool.purge_expired()
        assert purged == 2
        assert len(pool) == 0

    def test_ttl_zero_disables_expiration(self):
        pool = ConnectionPool(_factory, max_size=10, ttl_seconds=0)
        pool.get("a")
        purged = pool.purge_expired()
        assert purged == 0
        assert "a" in pool


class TestConnectionPoolThreadSafety:
    def test_concurrent_access(self):
        pool = ConnectionPool(_factory, max_size=100)
        errors = []

        def worker(start, end):
            try:
                for i in range(start, end):
                    pool.get(f"key-{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(i * 20, (i + 1) * 20))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(pool) == 100
