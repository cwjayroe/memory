from typing import Any
from constants import DEFAULT_RESPONSE_FORMAT, ALLOWED_RESPONSE_FORMATS, DEFAULT_EXCERPT_CHARS, MIN_EXCERPT_CHARS, MAX_EXCERPT_CHARS  # type: ignore


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()]
    if isinstance(value, list):
        tags = []
        for item in value:
            if isinstance(item, str) and item.strip():
                tags.append(item.strip())
        return tags
    return []


def normalize_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
        return items
    return []


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_project_ids(value: Any, *, max_projects: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            if isinstance(item, str):
                raw_items.append(item.strip())
    else:
        return []
    return dedupe_keep_order(raw_items)[:max_projects]

def normalize_response_format(value: Any) -> str:
    response_format = optional_str(value) or DEFAULT_RESPONSE_FORMAT
    if response_format not in ALLOWED_RESPONSE_FORMATS:
        return DEFAULT_RESPONSE_FORMAT
    return response_format


def normalize_excerpt_chars(value: Any) -> int:
    return max(
        MIN_EXCERPT_CHARS,
        min(
            safe_int(value, DEFAULT_EXCERPT_CHARS),
            MAX_EXCERPT_CHARS,
        ),
    )