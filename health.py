"""Health check utilities for project-memory MCP server.

Enterprise additions:
- Liveness probe (is the process alive and responsive?)
- Readiness probe (are all dependencies connected and warm?)
- Component-level checks with configurable timeouts
- Remote Chroma health check support
"""

from __future__ import annotations

import time
from typing import Any


def _check_ollama(ollama_base_url: str, model: str) -> dict[str, Any]:
    start = time.time()
    try:
        import urllib.request
        url = f"{ollama_base_url.rstrip('/')}/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            latency_ms = int((time.time() - start) * 1000)
            if resp.status == 200:
                return {"status": "ok", "latency_ms": latency_ms, "url": ollama_base_url, "model": model}
            return {"status": "degraded", "latency_ms": latency_ms, "detail": f"HTTP {resp.status}"}
    except Exception as exc:
        return {"status": "error", "latency_ms": int((time.time() - start) * 1000), "detail": str(exc)}


def _check_chroma(
    project_id: str,
    *,
    chroma_mode: str = "local",
    chroma_host: str = "localhost",
    chroma_port: int = 8000,
) -> dict[str, Any]:
    start = time.time()
    try:
        import chromadb
        if chroma_mode in ("remote", "client"):
            client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            client.heartbeat()
            latency_ms = int((time.time() - start) * 1000)
            return {
                "status": "ok",
                "latency_ms": latency_ms,
                "mode": "remote",
                "host": f"{chroma_host}:{chroma_port}",
            }
        else:
            import os
            from constants import MEMORY_ROOT  # type: ignore
            path = os.path.join(MEMORY_ROOT, project_id, "chroma")
            client = chromadb.PersistentClient(path=path)
            client.list_collections()
            latency_ms = int((time.time() - start) * 1000)
            return {"status": "ok", "latency_ms": latency_ms, "mode": "local", "path": path}
    except Exception as exc:
        return {"status": "error", "latency_ms": int((time.time() - start) * 1000), "detail": str(exc)}


def _check_embedding_model() -> dict[str, Any]:
    start = time.time()
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")
        _ = model.encode(["health check"])
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms, "model": "multi-qa-MiniLM-L6-cos-v1"}
    except Exception as exc:
        return {"status": "error", "latency_ms": int((time.time() - start) * 1000), "detail": str(exc)}


def _check_reranker(model_name: str) -> dict[str, Any]:
    start = time.time()
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(model_name)
        _ = model.predict([("health", "check")])
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms, "model": model_name}
    except Exception as exc:
        return {"status": "error", "latency_ms": int((time.time() - start) * 1000), "detail": str(exc)}


def _check_redis(redis_url: str) -> dict[str, Any]:
    """Check Redis connectivity (for distributed cache backend)."""
    start = time.time()
    try:
        import redis
        client = redis.Redis.from_url(redis_url, socket_timeout=3)
        client.ping()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms, "url": redis_url}
    except ImportError:
        return {"status": "skipped", "detail": "redis package not installed"}
    except Exception as exc:
        return {"status": "error", "latency_ms": int((time.time() - start) * 1000), "detail": str(exc)}


def liveness_check() -> dict[str, Any]:
    """Lightweight liveness probe: confirms the process is responsive.

    Suitable for Kubernetes livenessProbe — should never fail unless
    the process is deadlocked or OOM.
    """
    return {
        "status": "ok",
        "timestamp": time.time(),
    }


def readiness_check(
    *,
    ollama_base_url: str,
    ollama_model: str,
    reranker_model: str,
    default_project_id: str,
    chroma_mode: str = "local",
    chroma_host: str = "localhost",
    chroma_port: int = 8000,
    cache_backend: str = "memory",
    redis_url: str = "",
    skip_slow: bool = True,
    pool_stats: dict[str, Any] | None = None,
    cache_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Readiness probe: verifies all dependencies are available.

    Returns a detailed breakdown suitable for Kubernetes readinessProbe
    and operational dashboards.
    """
    results: dict[str, Any] = {}

    results["ollama"] = _check_ollama(ollama_base_url, ollama_model)
    results["chroma"] = _check_chroma(
        default_project_id,
        chroma_mode=chroma_mode,
        chroma_host=chroma_host,
        chroma_port=chroma_port,
    )

    if cache_backend == "redis" and redis_url:
        results["redis"] = _check_redis(redis_url)

    if not skip_slow:
        results["embedding_model"] = _check_embedding_model()
        results["reranker"] = _check_reranker(reranker_model)
    else:
        results["embedding_model"] = {"status": "skipped"}
        results["reranker"] = {"status": "skipped"}

    if pool_stats:
        results["connection_pool"] = pool_stats
    if cache_stats:
        results["search_cache"] = cache_stats

    statuses = [
        v.get("status", "error") for v in results.values()
        if isinstance(v, dict) and "status" in v
    ]
    if all(s in ("ok", "skipped") for s in statuses):
        overall = "ok"
    elif any(s == "error" for s in statuses):
        overall = "degraded"
    else:
        overall = "degraded"

    return {"overall": overall, "components": results}


def run_health_check(
    *,
    ollama_base_url: str,
    ollama_model: str,
    reranker_model: str,
    default_project_id: str,
    skip_slow: bool = False,
) -> dict[str, Any]:
    """Run all component health checks and return a combined result dict.

    Backwards-compatible entry point.
    """
    results: dict[str, Any] = {}

    results["ollama"] = _check_ollama(ollama_base_url, ollama_model)
    results["chroma"] = _check_chroma(default_project_id)

    if not skip_slow:
        results["embedding_model"] = _check_embedding_model()
        results["reranker"] = _check_reranker(reranker_model)
    else:
        results["embedding_model"] = {"status": "skipped"}
        results["reranker"] = {"status": "skipped"}

    statuses = [v.get("status", "error") for v in results.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif all(s in {"ok", "skipped"} for s in statuses):
        overall = "ok"
    elif any(s == "error" for s in statuses):
        overall = "degraded"
    else:
        overall = "degraded"

    return {"overall": overall, "components": results}
