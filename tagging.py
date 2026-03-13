"""Auto-tag suggestion for project-memory store operations."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower())


def _extract_candidate_tags(body: str, existing_tags: list[str], max_candidates: int = 10) -> list[str]:
    """Extract candidate tags from body text using TF-IDF-like scoring against existing vocabulary."""
    tokens = _tokenize(body)
    if not tokens:
        return []

    # Stop words to skip
    stop_words = {
        "the", "and", "for", "are", "was", "this", "that", "with", "from",
        "have", "has", "been", "will", "can", "not", "but", "its", "our",
        "their", "all", "use", "used", "when", "what", "which", "how",
        "should", "would", "could", "return", "returns", "value", "values",
        "type", "types", "def", "class", "function", "method", "param",
        "args", "kwargs", "self", "none", "true", "false", "str", "int",
        "list", "dict", "any", "bool",
    }

    counts = Counter(tok for tok in tokens if tok not in stop_words)
    total = sum(counts.values()) or 1

    # Score candidates: TF * log(length) to prefer longer, more specific terms
    scored: list[tuple[float, str]] = []
    for term, count in counts.items():
        tf = count / total
        length_bonus = math.log(len(term) + 1)
        score = tf * length_bonus
        scored.append((score, term))

    scored.sort(reverse=True)
    top_terms = [term for _, term in scored[:max_candidates * 2]]

    # Prefer terms that appear in existing tags vocabulary (boosted)
    existing_lower = {t.lower() for t in existing_tags}
    boosted = [t for t in top_terms if t in existing_lower]
    rest = [t for t in top_terms if t not in existing_lower]

    combined = boosted + rest
    return combined[:max_candidates]


def suggest_tags(
    body: str,
    *,
    existing_tag_vocab: list[str] | None = None,
    max_suggestions: int = 5,
) -> list[str]:
    """Suggest tags for a memory body. Returns a list of suggested tag strings."""
    vocab = existing_tag_vocab or []
    candidates = _extract_candidate_tags(body, vocab, max_candidates=max_suggestions * 2)
    return candidates[:max_suggestions]
