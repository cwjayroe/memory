"""Scope summary generation using the configured LLM (Ollama)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _build_summary_prompt(
    project_id: str,
    samples_by_category: dict[str, list[str]],
) -> str:
    lines = [
        f"You are summarizing the memory scope '{project_id}' for a developer.",
        "Below are representative memory excerpts grouped by category.",
        "Write a concise (3-10 sentence) plain-English summary covering:",
        "- What this scope is about",
        "- Key decisions or architecture choices",
        "- Main repos/modules covered",
        "- Any recurring themes or important context",
        "",
    ]
    for category, excerpts in sorted(samples_by_category.items()):
        lines.append(f"[{category.upper()}]")
        for excerpt in excerpts[:3]:
            lines.append(f"  - {excerpt[:300]}")
        lines.append("")
    lines.append("Summary:")
    return "\n".join(lines)


def generate_scope_summary(
    *,
    project_id: str,
    items: list[Any],
    repo: str | None = None,
    category: str | None = None,
    max_tokens: int = 800,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2",
) -> str:
    """Generate a prose summary of a scope's contents using Ollama."""
    from .helpers import _coerce_memory_item

    samples_by_category: dict[str, list[str]] = defaultdict(list)
    for raw_item in items:
        item = _coerce_memory_item(raw_item)
        md = item.metadata
        if repo and md.repo != repo:
            continue
        if category and md.category != category:
            continue
        cat = md.category or "general"
        if len(samples_by_category[cat]) < 5:
            excerpt = " ".join(item.memory.split())[:400]
            samples_by_category[cat].append(excerpt)

    if not samples_by_category:
        return f"No memories found for project={project_id}" + (f" repo={repo}" if repo else "") + (f" category={category}" if category else "") + "."

    prompt = _build_summary_prompt(project_id, dict(samples_by_category))

    try:
        import urllib.request
        import json

        payload = json.dumps({
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{ollama_base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip() or "(empty response from LLM)"
    except Exception as exc:
        return f"Summary generation failed: {exc}"
