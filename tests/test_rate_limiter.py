"""Tests for the rate_limiter module."""

import time
import pytest
from rate_limiter import RateLimiter, RateLimitConfig, DEFAULT_LIMITS


class TestRateLimiterBasic:
    def test_allows_within_burst(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=10.0, burst=5)},
        )
        for _ in range(5):
            assert limiter.allow("user1") is True

    def test_rejects_after_burst_exhausted(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=0.1, burst=2)},
        )
        assert limiter.allow("user1") is True
        assert limiter.allow("user1") is True
        assert limiter.allow("user1") is False

    def test_disabled_always_allows(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=0.001, burst=1)},
            enabled=False,
        )
        assert limiter.allow("user1") is True
        assert limiter.allow("user1") is True

    def test_separate_keys_have_separate_buckets(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=0.1, burst=1)},
        )
        assert limiter.allow("user1") is True
        assert limiter.allow("user2") is True
        assert limiter.allow("user1") is False  # user1 exhausted
        assert limiter.allow("user2") is False  # user2 exhausted


class TestRateLimiterOperations:
    def test_different_operations_use_different_configs(self):
        limiter = RateLimiter(
            limits={
                "search": RateLimitConfig(rate=0.1, burst=2),
                "store": RateLimitConfig(rate=0.1, burst=5),
            },
        )
        # Search: burst of 2 (key includes operation via caller convention)
        assert limiter.allow("search:u1", operation="search") is True
        assert limiter.allow("search:u1", operation="search") is True
        assert limiter.allow("search:u1", operation="search") is False

        # Store: burst of 5, separate key
        for _ in range(5):
            assert limiter.allow("store:u1", operation="store") is True


class TestRateLimiterRefill:
    def test_tokens_refill_over_time(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=100.0, burst=2)},
        )
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is False
        time.sleep(0.05)  # refill ~5 tokens at 100/s
        assert limiter.allow("u1") is True


class TestRateLimiterWaitTime:
    def test_wait_time_zero_when_available(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=10.0, burst=5)},
        )
        assert limiter.wait_time("u1") == 0.0

    def test_wait_time_positive_when_exhausted(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=1.0, burst=1)},
        )
        limiter.allow("u1")  # exhaust
        wt = limiter.wait_time("u1")
        assert wt > 0


class TestRateLimiterMaintenance:
    def test_purge_stale_buckets(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=10.0, burst=5)},
        )
        limiter.allow("u1")
        limiter.allow("u2")
        time.sleep(0.05)
        purged = limiter.purge_stale(max_age_seconds=0.01)
        assert purged == 2

    def test_stats(self):
        limiter = RateLimiter(
            limits={"default": RateLimitConfig(rate=0.1, burst=1)},
        )
        limiter.allow("u1")  # allowed
        limiter.allow("u1")  # rejected
        stats = limiter.stats()
        assert stats["total_allowed"] == 1
        assert stats["total_rejected"] == 1
        assert stats["active_buckets"] == 1


class TestRateLimitConfig:
    def test_invalid_values_are_clamped(self):
        cfg = RateLimitConfig(rate=-1, burst=-5)
        assert cfg.rate == 1.0
        assert cfg.burst == 1
