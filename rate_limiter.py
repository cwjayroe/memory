"""Token-bucket rate limiter for MCP handler protection.

Enterprise deployments need protection against:
- Runaway agent loops issuing thousands of searches per minute
- Bulk ingestion flooding that starves search queries
- Single-tenant abuse in multi-tenant setups

This module provides a per-key token-bucket rate limiter that can be
applied per-operation, per-tenant, or per-project_id.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RateLimitConfig:
    """Configuration for a rate limit bucket.

    Parameters
    ----------
    rate:
        Tokens added per second (sustained throughput).
    burst:
        Maximum tokens in the bucket (peak burst capacity).
    """
    rate: float
    burst: int

    def __post_init__(self) -> None:
        if self.rate <= 0:
            object.__setattr__(self, "rate", 1.0)
        if self.burst <= 0:
            object.__setattr__(self, "burst", 1)


# Sensible defaults for enterprise workloads
DEFAULT_LIMITS: dict[str, RateLimitConfig] = {
    "search": RateLimitConfig(rate=10.0, burst=30),
    "store": RateLimitConfig(rate=20.0, burst=60),
    "bulk_store": RateLimitConfig(rate=5.0, burst=10),
    "list": RateLimitConfig(rate=15.0, burst=40),
    "delete": RateLimitConfig(rate=10.0, burst=20),
    "ingest": RateLimitConfig(rate=3.0, burst=8),
    "default": RateLimitConfig(rate=20.0, burst=50),
}


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    config: RateLimitConfig


class RateLimiter:
    """Thread-safe, per-key token-bucket rate limiter.

    Keys are typically ``f"{operation}:{tenant_id}"`` or just ``operation``.
    """

    def __init__(
        self,
        limits: dict[str, RateLimitConfig] | None = None,
        *,
        enabled: bool = True,
    ):
        self._limits = limits or DEFAULT_LIMITS
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._enabled = enabled
        self._total_allowed = 0
        self._total_rejected = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get_config(self, operation: str) -> RateLimitConfig:
        return self._limits.get(operation, self._limits.get("default", RateLimitConfig(rate=20.0, burst=50)))

    def allow(self, key: str, operation: str = "default", tokens: int = 1) -> bool:
        """Check whether *tokens* requests are allowed for *key*.

        Returns True if allowed, False if rate-limited.
        """
        if not self._enabled:
            return True

        config = self._get_config(operation)
        now = time.monotonic()

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(
                    tokens=float(config.burst),
                    last_refill=now,
                    config=config,
                )
                self._buckets[key] = bucket

            # Refill tokens based on elapsed time
            elapsed = now - bucket.last_refill
            bucket.tokens = min(
                float(config.burst),
                bucket.tokens + elapsed * config.rate,
            )
            bucket.last_refill = now

            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                self._total_allowed += 1
                return True

            self._total_rejected += 1
            return False

    def wait_time(self, key: str, operation: str = "default", tokens: int = 1) -> float:
        """Return seconds to wait before *tokens* would be available. 0 if available now."""
        if not self._enabled:
            return 0.0

        config = self._get_config(operation)
        now = time.monotonic()

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0

            elapsed = now - bucket.last_refill
            available = min(float(config.burst), bucket.tokens + elapsed * config.rate)
            if available >= tokens:
                return 0.0
            deficit = tokens - available
            return deficit / config.rate

    def purge_stale(self, max_age_seconds: float = 300.0) -> int:
        """Remove buckets not accessed within *max_age_seconds*."""
        now = time.monotonic()
        purged = 0
        with self._lock:
            stale_keys = [
                key for key, bucket in self._buckets.items()
                if (now - bucket.last_refill) > max_age_seconds
            ]
            for key in stale_keys:
                del self._buckets[key]
                purged += 1
        return purged

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "active_buckets": len(self._buckets),
                "total_allowed": self._total_allowed,
                "total_rejected": self._total_rejected,
            }
