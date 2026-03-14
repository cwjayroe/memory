"""Pluggable search cache backends for enterprise deployments.

The default in-process LRU cache works for single-instance deployments.
For horizontal scaling (multiple MCP server replicas behind a load balancer),
a shared cache backend (Redis) ensures cache coherence across instances.

Usage in server_config:
    CACHE_BACKEND=memory   -> InProcessCache (default, zero dependencies)
    CACHE_BACKEND=redis    -> RedisCache (requires redis-py)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Observable counters for any cache backend."""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    errors: int = 0


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Return cached payload or None."""

    @abstractmethod
    def set(self, key: str, payload: str, ttl_seconds: float) -> None:
        """Store payload with TTL."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a specific key."""

    @abstractmethod
    def clear(self) -> None:
        """Flush all entries."""

    @abstractmethod
    def stats(self) -> CacheStats:
        """Return current counters."""


class InProcessCache(CacheBackend):
    """Thread-safe in-process LRU cache with TTL.

    This is the default backend.  It requires no external dependencies and
    works well for single-instance deployments.
    """

    def __init__(self, *, max_entries: int = 128, default_ttl: float = 60.0):
        self._max_entries = max(1, max_entries)
        self._default_ttl = max(0.0, default_ttl)
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = CacheStats()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            expires_at, payload = entry
            if time.time() >= expires_at:
                self._store.pop(key, None)
                self._stats.misses += 1
                return None
            self._store.move_to_end(key)
            self._stats.hits += 1
            return payload

    def set(self, key: str, payload: str, ttl_seconds: float = 0) -> None:
        ttl = ttl_seconds if ttl_seconds > 0 else self._default_ttl
        with self._lock:
            self._store[key] = (time.time() + ttl, payload)
            self._store.move_to_end(key)
            self._stats.sets += 1
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                self._stats.evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                sets=self._stats.sets,
                evictions=self._stats.evictions,
                errors=self._stats.errors,
            )


class RedisCache(CacheBackend):
    """Redis-backed shared cache for multi-instance deployments.

    Requires ``redis`` package.  Gracefully degrades to cache misses on
    connection failures (circuit-breaker pattern).
    """

    def __init__(
        self,
        *,
        url: str = "redis://localhost:6379/0",
        key_prefix: str = "pmem:",
        default_ttl: float = 60.0,
        socket_timeout: float = 2.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 30.0,
    ):
        self._key_prefix = key_prefix
        self._default_ttl = max(1.0, default_ttl)
        self._stats = CacheStats()
        self._lock = threading.Lock()

        # Circuit breaker state
        self._consecutive_errors = 0
        self._circuit_open_until: float = 0.0
        self._cb_threshold = circuit_breaker_threshold
        self._cb_reset_seconds = circuit_breaker_reset_seconds

        try:
            import redis
            self._client = redis.Redis.from_url(
                url,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                decode_responses=True,
            )
        except Exception as exc:
            LOGGER.warning("Redis unavailable, cache will always miss: %s", exc)
            self._client = None
            self._stats.errors += 1

    def _circuit_open(self) -> bool:
        if self._consecutive_errors >= self._cb_threshold:
            if time.time() < self._circuit_open_until:
                return True
            # Half-open: reset and allow one attempt
            self._consecutive_errors = 0
        return False

    def _record_error(self) -> None:
        with self._lock:
            self._consecutive_errors += 1
            self._stats.errors += 1
            if self._consecutive_errors >= self._cb_threshold:
                self._circuit_open_until = time.time() + self._cb_reset_seconds

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_errors = 0

    def _full_key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    def get(self, key: str) -> str | None:
        if self._client is None or self._circuit_open():
            self._stats.misses += 1
            return None
        try:
            value = self._client.get(self._full_key(key))
            self._record_success()
            if value is None:
                self._stats.misses += 1
                return None
            self._stats.hits += 1
            return str(value)
        except Exception:
            self._record_error()
            self._stats.misses += 1
            return None

    def set(self, key: str, payload: str, ttl_seconds: float = 0) -> None:
        if self._client is None or self._circuit_open():
            return
        ttl = ttl_seconds if ttl_seconds > 0 else self._default_ttl
        try:
            self._client.setex(self._full_key(key), int(ttl), payload)
            self._record_success()
            self._stats.sets += 1
        except Exception:
            self._record_error()

    def delete(self, key: str) -> None:
        if self._client is None or self._circuit_open():
            return
        try:
            self._client.delete(self._full_key(key))
            self._record_success()
        except Exception:
            self._record_error()

    def clear(self) -> None:
        if self._client is None or self._circuit_open():
            return
        try:
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor, match=f"{self._key_prefix}*", count=100)
                if keys:
                    self._client.delete(*keys)
                if cursor == 0:
                    break
            self._record_success()
        except Exception:
            self._record_error()

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._stats.hits,
            misses=self._stats.misses,
            sets=self._stats.sets,
            evictions=self._stats.evictions,
            errors=self._stats.errors,
        )


def create_cache_backend(
    backend: str = "memory",
    *,
    max_entries: int = 128,
    default_ttl: float = 60.0,
    redis_url: str = "redis://localhost:6379/0",
    redis_key_prefix: str = "pmem:",
) -> CacheBackend:
    """Factory for creating cache backends from configuration."""
    if backend == "redis":
        return RedisCache(
            url=redis_url,
            key_prefix=redis_key_prefix,
            default_ttl=default_ttl,
        )
    return InProcessCache(max_entries=max_entries, default_ttl=default_ttl)
