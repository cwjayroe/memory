"""Tests for enterprise health check additions."""

import pytest
from health import liveness_check, readiness_check


class TestLivenessCheck:
    def test_always_returns_ok(self):
        result = liveness_check()
        assert result["status"] == "ok"
        assert "timestamp" in result


class TestReadinessCheck:
    def test_returns_structured_result(self):
        result = readiness_check(
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3.2",
            reranker_model="BAAI/bge-reranker-base",
            default_project_id="test",
            skip_slow=True,
        )
        assert "overall" in result
        assert "components" in result
        assert "ollama" in result["components"]
        assert "chroma" in result["components"]

    def test_includes_pool_and_cache_stats(self):
        pool_stats = {"hits": 10, "misses": 2}
        cache_stats = {"hits": 5, "misses": 1}
        result = readiness_check(
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3.2",
            reranker_model="BAAI/bge-reranker-base",
            default_project_id="test",
            skip_slow=True,
            pool_stats=pool_stats,
            cache_stats=cache_stats,
        )
        assert result["components"]["connection_pool"] == pool_stats
        assert result["components"]["search_cache"] == cache_stats

    def test_remote_chroma_mode(self):
        result = readiness_check(
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3.2",
            reranker_model="BAAI/bge-reranker-base",
            default_project_id="test",
            chroma_mode="remote",
            chroma_host="chroma-server",
            chroma_port=8000,
            skip_slow=True,
        )
        # Will fail connection but should not crash
        assert "chroma" in result["components"]
