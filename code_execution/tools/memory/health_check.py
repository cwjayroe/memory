"""health_check — Check connectivity and readiness of all system components: Ollama, Chroma, embedding model, and reranker."""

from __future__ import annotations

from code_execution.bridge import call_tool


def health_check(
    skip_slow: bool = False,
) -> str:
    """Check connectivity and readiness of all system components: Ollama, Chroma, embedding model, and reranker.

    Args:
        skip_slow: Skip slow model-load checks (embedding + reranker) (optional)"""
    kwargs: dict = {}
    if skip_slow is not None:
        kwargs["skip_slow"] = skip_slow
    return call_tool("health_check", **kwargs)
