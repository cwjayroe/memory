"""Tests for the metrics module."""

import json
import logging
import pytest
from metrics import (
    MetricsRegistry,
    OperationTimer,
    StructuredFormatter,
    new_correlation_id,
    get_correlation_id,
    correlation_id,
)


class TestMetricsRegistry:
    def test_increment_counter(self):
        reg = MetricsRegistry()
        reg.increment("test.counter")
        reg.increment("test.counter", 5)
        assert reg.counter_value("test.counter") == 6

    def test_counter_default_zero(self):
        reg = MetricsRegistry()
        assert reg.counter_value("nonexistent") == 0

    def test_observe_histogram(self):
        reg = MetricsRegistry()
        reg.observe("latency", 10.0)
        reg.observe("latency", 20.0)
        reg.observe("latency", 30.0)

        snap = reg.snapshot()
        h = snap["histograms"]["latency"]
        assert h["count"] == 3
        assert h["min"] == 10.0
        assert h["max"] == 30.0
        assert h["avg"] == 20.0

    def test_snapshot_includes_uptime(self):
        reg = MetricsRegistry()
        snap = reg.snapshot()
        assert "uptime_seconds" in snap
        assert snap["uptime_seconds"] >= 0

    def test_reset_clears_all(self):
        reg = MetricsRegistry()
        reg.increment("x")
        reg.observe("y", 1.0)
        reg.reset()
        assert reg.counter_value("x") == 0
        snap = reg.snapshot()
        assert "y" not in snap["histograms"]


class TestOperationTimer:
    def test_records_duration(self):
        reg = MetricsRegistry()
        with OperationTimer("test_op_ms", registry=reg):
            pass  # fast operation

        snap = reg.snapshot()
        assert "test_op_ms" in snap["histograms"]
        assert snap["histograms"]["test_op_ms"]["count"] == 1
        assert snap["histograms"]["test_op_ms"]["min"] >= 0


class TestCorrelationId:
    def test_new_correlation_id(self):
        cid = new_correlation_id()
        assert len(cid) == 12
        assert cid == get_correlation_id()

    def test_get_generates_if_absent(self):
        correlation_id.set("")
        cid = get_correlation_id()
        assert len(cid) == 12


class TestStructuredFormatter:
    def test_formats_as_json(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "test message"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert "correlation_id" in data
        assert "ts" in data
