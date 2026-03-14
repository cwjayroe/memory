"""Connection pool with LRU eviction, TTL, and max-size enforcement for Memory instances.

Enterprise environments may have hundreds of project scopes. Keeping every Memory
instance alive forever leaks file descriptors, Chroma connections, and RAM.  This
module replaces the simple dict cache in MemoryManager with a bounded, thread-safe
pool that:

- Evicts least-recently-used entries when the pool exceeds ``max_size``.
- Expires entries that have not been accessed within ``ttl_seconds``.
- Tracks hit/miss/eviction counts for observability.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class PoolStats:
    """Observable counters for the connection pool."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    current_size: int = 0


@dataclass
class _PoolEntry(Generic[T]):
    value: T
    created_at: float
    last_accessed: float


class ConnectionPool(Generic[T]):
    """Thread-safe, LRU-evicting connection pool with TTL.

    Parameters
    ----------
    factory:
        Callable that receives a ``key`` string and returns a new ``T`` instance.
    max_size:
        Maximum number of live entries.  When exceeded the least-recently-used
        entry is evicted.  Defaults to 64.
    ttl_seconds:
        Seconds after last access before an entry is considered stale.
        Set to 0 to disable TTL.  Defaults to 3600 (1 hour).
    on_evict:
        Optional callback invoked with ``(key, value)`` when an entry is evicted
        or expired, allowing callers to release external resources.
    """

    def __init__(
        self,
        factory: Callable[[str], T],
        *,
        max_size: int = 64,
        ttl_seconds: float = 3600.0,
        on_evict: Callable[[str, T], None] | None = None,
    ):
        self._factory = factory
        self._max_size = max(1, max_size)
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._on_evict = on_evict
        self._entries: OrderedDict[str, _PoolEntry[T]] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = PoolStats()

    @property
    def stats(self) -> PoolStats:
        with self._lock:
            self._stats.current_size = len(self._entries)
            return PoolStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                current_size=len(self._entries),
            )

    def get(self, key: str) -> T:
        """Retrieve or create an entry for *key*."""
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if self._ttl_seconds > 0 and (now - entry.last_accessed) > self._ttl_seconds:
                    self._expire_entry(key)
                else:
                    entry.last_accessed = now
                    self._entries.move_to_end(key)
                    self._stats.hits += 1
                    return entry.value

            self._stats.misses += 1
            value = self._factory(key)
            self._entries[key] = _PoolEntry(
                value=value,
                created_at=now,
                last_accessed=now,
            )
            self._entries.move_to_end(key)
            self._enforce_max_size()
            return value

    def remove(self, key: str) -> None:
        """Explicitly remove an entry (e.g. after a transient error)."""
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is not None and self._on_evict:
                self._on_evict(key, entry.value)

    def clear(self) -> None:
        """Evict all entries."""
        with self._lock:
            if self._on_evict:
                for key, entry in self._entries.items():
                    self._on_evict(key, entry.value)
            self._entries.clear()

    def purge_expired(self) -> int:
        """Remove all expired entries.  Returns count of purged entries."""
        if self._ttl_seconds <= 0:
            return 0
        now = time.monotonic()
        purged = 0
        with self._lock:
            expired_keys = [
                key
                for key, entry in self._entries.items()
                if (now - entry.last_accessed) > self._ttl_seconds
            ]
            for key in expired_keys:
                self._expire_entry(key)
                purged += 1
        return purged

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._entries.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._entries

    # -- internal helpers (caller must hold _lock) ---

    def _expire_entry(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._stats.expirations += 1
            if self._on_evict:
                self._on_evict(key, entry.value)

    def _enforce_max_size(self) -> None:
        while len(self._entries) > self._max_size:
            oldest_key, oldest_entry = self._entries.popitem(last=False)
            self._stats.evictions += 1
            if self._on_evict:
                self._on_evict(oldest_key, oldest_entry.value)
