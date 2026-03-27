from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SearchResult:
    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEntry:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
