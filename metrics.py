"""Structured logging and metrics for enterprise observability.

Provides:
- Correlation IDs (request tracing across async operations)
- Structured JSON log formatter
- Counters and histograms for key operations
- Export-ready metrics snapshot for health endpoints
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# Correlation ID propagated through async call chains
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def new_correlation_id() -> str:
    """Generate and set a new correlation ID for the current context."""
    cid = uuid.uuid4().hex[:12]
    correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """Return the current correlation ID, generating one if absent."""
    cid = correlation_id.get()
    if not cid:
        cid = new_correlation_id()
    return cid


class StructuredFormatter(logging.Formatter):
    """Emit log records as single-line JSON with correlation ID."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
        # Merge any extra fields attached to the record
        for key in ("operation", "project_id", "duration_ms", "result_count", "tenant_id"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, default=str)


@dataclass
class _HistogramBucket:
    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value < self.min_val:
            self.min_val = value
        if value > self.max_val:
            self.max_val = value

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "total": round(self.total, 3),
            "min": round(self.min_val, 3) if self.count > 0 else 0,
            "max": round(self.max_val, 3) if self.count > 0 else 0,
            "avg": round(self.total / self.count, 3) if self.count > 0 else 0,
        }


class MetricsRegistry:
    """Thread-safe metrics registry for counters and histograms.

    Designed for low overhead: no external dependencies, lock-free reads
    for counters, single lock for histogram observations.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, _HistogramBucket] = defaultdict(_HistogramBucket)
        self._lock = threading.Lock()
        self._start_time = time.monotonic()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._histograms[name].observe(value)

    def counter_value(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of all metrics."""
        with self._lock:
            return {
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
                "counters": dict(self._counters),
                "histograms": {
                    name: bucket.as_dict()
                    for name, bucket in self._histograms.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._start_time = time.monotonic()


# Global singleton – import and use directly
METRICS = MetricsRegistry()


class OperationTimer:
    """Context manager that records operation duration to a histogram.

    Usage::

        with OperationTimer("search_duration_ms"):
            result = await do_search()
    """

    def __init__(self, metric_name: str, registry: MetricsRegistry | None = None):
        self._name = metric_name
        self._registry = registry or METRICS
        self._start: float = 0.0

    def __enter__(self) -> "OperationTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._registry.observe(self._name, elapsed_ms)


def configure_structured_logging(
    level: int = logging.INFO,
    logger_name: str | None = None,
) -> None:
    """Replace the root (or named) logger's handlers with structured JSON output."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.handlers = [handler]
