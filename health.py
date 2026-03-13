"""Health check utilities for project-memory MCP server."""

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


def _check_chroma(project_id: str) -> dict[str, Any]:
    start = time.time()
    try:
        import chromadb
        import os
        from constants import MEMORY_ROOT  # type: ignore
        path = os.path.join(MEMORY_ROOT, project_id, "chroma")
        client = chromadb.PersistentClient(path=path)
        # Attempt a list collections call to verify read/write access
        client.list_collections()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms, "path": path}
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


def run_health_check(
    *,
    ollama_base_url: str,
    ollama_model: str,
    reranker_model: str,
    default_project_id: str,
    skip_slow: bool = False,
) -> dict[str, Any]:
    """Run all component health checks and return a combined result dict."""
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
