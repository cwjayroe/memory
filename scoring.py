"""Scoring, deduplication, and candidate packing for project-memory search."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rank_bm25 import BM25Okapi

from constants import DEFAULT_PROJECT_ID 
from memory_types import MemoryItem
from helpers import normalize_tags, parse_datetime  

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoringWeights:
    """Component weights for the hybrid scoring formula.

    Used in both pre-rerank scoring and final score computation,
    eliminating the prior duplication of weight constants.
    """

    vector: float = 0.30
    lexical: float = 0.20
    metadata: float = 0.15
    recency: float = 0.10
    rerank: float = 0.25


@dataclass(frozen=True)
class PackingConfig:
    """Diversity and budget constraints for candidate packing."""

    max_repo_results: int = 3
    max_category_results: int = 3
    decision_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"decision", "architecture"})
    )


# ---------------------------------------------------------------------------
# Stateless helpers (no instance state, used by ScoringEngine & RerankerManager)
# ---------------------------------------------------------------------------


def get_metadata(memory_item: MemoryItem | dict[str, Any]) -> dict[str, Any]:
    """Extract metadata dict from a MemoryItem or raw dict."""
    if isinstance(memory_item, MemoryItem):
        return memory_item.metadata.as_dict()
    metadata = memory_item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def raw_distance_value(memory_item: dict[str, Any]) -> float:
    distance = memory_item.get("score")
    if isinstance(distance, (int, float)):
        return float(distance)
    return float("inf")


def distance_similarity(distance: float) -> float:
    return 1.0 / (1.0 + max(distance, 0.0))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return int(math.ceil(len(text) / 4.0))


def normalize_score_values(values: list[float]) -> list[float]:
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        return [1.0 if value > 0 else 0.0 for value in values]
    return [(value - min_v) / (max_v - min_v) for value in values]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_./:-]+", text.lower())


def lexical_document(memory_item: dict[str, Any]) -> str:
    metadata = get_metadata(memory_item)
    tags = normalize_tags(metadata.get("tags"))
    body = str(memory_item.get("memory", ""))
    parts = [
        body,
        str(metadata.get("repo", "")),
        str(metadata.get("source_path", "")),
        str(metadata.get("category", "")),
        str(metadata.get("source_kind", "")),
        str(metadata.get("module", "")),
        " ".join(tags),
    ]
    return " ".join(parts).strip()


def lexical_components(query: str, candidates: list[dict[str, Any]]) -> list[float]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return [0.0 for _ in candidates]

    corpora = [tokenize(lexical_document(item)) for item in candidates]

    try:
        bm25 = BM25Okapi(corpora)
        scores = [float(value) for value in bm25.get_scores(query_tokens)]
        return normalize_score_values(scores)
    except Exception:
        LOGGER.warning("BM25 lexical scoring failed; falling back to overlap scoring", exc_info=True)

    query_set = set(query_tokens)
    overlap_scores: list[float] = []
    for doc_tokens in corpora:
        doc_set = set(doc_tokens)
        if not doc_set:
            overlap_scores.append(0.0)
            continue
        overlap_scores.append(len(query_set.intersection(doc_set)) / float(len(query_set)))
    return overlap_scores


def recency_component(memory_item: dict[str, Any], now_utc: datetime) -> float:
    metadata = get_metadata(memory_item)
    updated_at = parse_datetime(metadata.get("updated_at"))
    if updated_at is None:
        return 0.2
    age_days = max((now_utc - updated_at).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / 30.0)


def dedupe_key(memory_item: dict[str, Any], default_project_id: str = DEFAULT_PROJECT_ID) -> str:
    metadata = get_metadata(memory_item)
    project_id = str(memory_item.get("_project_id") or metadata.get("project_id") or default_project_id)

    upsert_key = metadata.get("upsert_key")
    if isinstance(upsert_key, str) and upsert_key.strip():
        return f"upsert::{upsert_key.strip()}"

    repo = str(metadata.get("repo") or "")
    source_path = str(metadata.get("source_path") or "")
    fingerprint = metadata.get("fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return f"fingerprint::{project_id}::{repo}::{source_path}::{fingerprint.strip()}"

    memory_text = " ".join(str(memory_item.get("memory", "")).split())
    fallback_raw = f"{project_id}::{repo}::{source_path}::{memory_text}"
    fallback_hash = hashlib.sha256(fallback_raw.encode("utf-8")).hexdigest()
    return f"fallback::{fallback_hash}"


# ---------------------------------------------------------------------------
# RerankerManager
# ---------------------------------------------------------------------------


class RerankerManager:
    """Thread-safe lazy-loaded reranker model lifecycle manager."""

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model: Any = None
        self._load_error: str | None = None
        self._lock = threading.Lock()

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def get(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._load_error:
            return None

        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_error:
                return None
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self._model_name)
                return self._model
            except Exception as exc:  # pragma: no cover - environment dependent
                self._load_error = str(exc)
                LOGGER.warning(
                    "Reranker unavailable. Falling back to hybrid ranking without reranker: %s",
                    exc,
                )
                return None

    def apply(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> bool:
        model = self.get()
        if model is None or top_n <= 0 or not candidates:
            return False

        top_n = min(top_n, len(candidates))
        top_candidates = sorted(
            candidates,
            key=lambda item: float(item.get("_pre_rerank_score", 0.0)),
            reverse=True,
        )[:top_n]

        pairs = [(query, lexical_document(item)) for item in top_candidates]
        try:
            raw_scores = model.predict(pairs)
            if hasattr(raw_scores, "tolist"):
                raw_scores = raw_scores.tolist()
            score_values = [float(value) for value in raw_scores]
        except Exception:  # pragma: no cover - environment dependent
            LOGGER.warning("Reranker scoring failed; using pre-rerank score fallback", exc_info=True)
            return False

        normalized = normalize_score_values(score_values)
        for item, score in zip(top_candidates, normalized):
            components = item.get("_score_components", {})
            components["rerank_component"] = score
            item["_score_components"] = components
        return True


# ---------------------------------------------------------------------------
# ScoringEngine
# ---------------------------------------------------------------------------


class ScoringEngine:
    """Orchestrates candidate scoring, deduplication, and packing."""

    def __init__(
        self,
        *,
        weights: ScoringWeights | None = None,
        reranker: RerankerManager | None = None,
        packing: PackingConfig | None = None,
        default_project_id: str = DEFAULT_PROJECT_ID,
    ):
        self.weights = weights or ScoringWeights()
        self.reranker = reranker or RerankerManager("BAAI/bge-reranker-base")
        self.packing = packing or PackingConfig()
        self._default_project_id = default_project_id

    def _metadata_component(
        self,
        memory_item: dict[str, Any],
        *,
        repo: str | None,
        path_prefix: str | None,
        tags: list[str],
        categories: list[str],
    ) -> float:
        metadata = get_metadata(memory_item)
        score = 0.0

        if repo and metadata.get("repo") == repo:
            score += 0.35
        if path_prefix:
            source_path = metadata.get("source_path")
            if isinstance(source_path, str) and source_path.startswith(path_prefix):
                score += 0.20
        if categories:
            category = metadata.get("category")
            if category in categories:
                score += 0.15
        if tags:
            memory_tags = normalize_tags(metadata.get("tags"))
            if set(tags).intersection(memory_tags):
                score += 0.15
        if metadata.get("category") in self.packing.decision_categories:
            score += 0.15

        # Priority boost/penalty
        priority = metadata.get("priority", "normal")
        if priority == "high":
            score += 0.20
        elif priority == "low":
            score -= 0.10

        return min(max(score, 0.0), 1.0)

    def score_candidates(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        repo: str | None,
        path_prefix: str | None,
        tags: list[str],
        categories: list[str],
        ranking_mode: str,
        rerank_top_n: int,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        w = self.weights
        now_utc = datetime.now(timezone.utc)
        lexical = lexical_components(query, candidates)
        pre_scores: list[float] = []

        for idx, item in enumerate(candidates):
            distance = raw_distance_value(item)
            item["_distance"] = distance if math.isfinite(distance) else None

            vector_comp = distance_similarity(distance) if math.isfinite(distance) else 0.0
            lexical_comp = lexical[idx] if idx < len(lexical) else 0.0
            metadata_comp = self._metadata_component(
                item,
                repo=repo,
                path_prefix=path_prefix,
                tags=tags,
                categories=categories,
            )
            recency_comp = recency_component(item, now_utc)
            pre_score = (
                w.vector * vector_comp
                + w.lexical * lexical_comp
                + w.metadata * metadata_comp
                + w.recency * recency_comp
            )
            pre_scores.append(pre_score)
            item["_pre_rerank_score"] = pre_score
            item["_score_components"] = {
                "vector_component": vector_comp,
                "lexical_component": lexical_comp,
                "metadata_component": metadata_comp,
                "recency_component": recency_comp,
                "rerank_component": 0.0,
                "final_score": 0.0,
            }

        pre_norm = normalize_score_values(pre_scores)
        for idx, item in enumerate(candidates):
            components = item["_score_components"]
            components["rerank_component"] = pre_norm[idx] if idx < len(pre_norm) else 0.0

        if ranking_mode == "hybrid_weighted_rerank":
            pass

        sorted_candidates = sorted(
            candidates,
            key=lambda item: float(item.get("_pre_rerank_score", 0.0)),
            reverse=True,
        )
        return sorted_candidates

    def finalize_scores(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        w = self.weights
        for item in candidates:
            components = item.get("_score_components", {})
            final_score = (
                w.vector * float(components.get("vector_component", 0.0))
                + w.lexical * float(components.get("lexical_component", 0.0))
                + w.metadata * float(components.get("metadata_component", 0.0))
                + w.recency * float(components.get("recency_component", 0.0))
                + w.rerank * float(components.get("rerank_component", 0.0))
            )
            components["final_score"] = final_score
            item["_score_components"] = components
            item["score"] = final_score

        return sorted(candidates, key=lambda item: float(item.get("score", 0.0)), reverse=True)

    def dedupe_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in candidates:
            key = dedupe_key(item, self._default_project_id)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = item
                continue
            if raw_distance_value(item) < raw_distance_value(existing):
                deduped[key] = item
        return list(deduped.values())

    def _candidate_repo_key(self, memory_item: dict[str, Any]) -> tuple[str, str]:
        metadata = get_metadata(memory_item)
        project_id = str(
            memory_item.get("_project_id")
            or metadata.get("project_id")
            or self._default_project_id
        )
        repo = str(metadata.get("repo") or "unknown-repo")
        return (project_id, repo)

    def _candidate_category(self, memory_item: dict[str, Any]) -> str:
        metadata = get_metadata(memory_item)
        return str(metadata.get("category") or "general")

    def pack_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        token_budget: int,
    ) -> list[dict[str, Any]]:
        if not candidates or limit <= 0 or token_budget <= 0:
            return []

        p = self.packing
        selected: list[dict[str, Any]] = []
        selected_ids: set[int] = set()
        repo_counts: dict[tuple[str, str], int] = defaultdict(int)
        category_counts: dict[str, int] = defaultdict(int)
        remaining_budget = token_budget

        def try_select(item: dict[str, Any], *, enforce_caps: bool) -> bool:
            nonlocal remaining_budget
            item_id = id(item)
            if item_id in selected_ids:
                return False

            token_cost = estimate_tokens(str(item.get("memory", "")))
            if token_cost > remaining_budget:
                return False

            repo_key = self._candidate_repo_key(item)
            category = self._candidate_category(item)
            if enforce_caps:
                if repo_counts[repo_key] >= p.max_repo_results:
                    return False
                if category_counts[category] >= p.max_category_results:
                    return False

            selected.append(item)
            selected_ids.add(item_id)
            repo_counts[repo_key] += 1
            category_counts[category] += 1
            remaining_budget -= token_cost
            return True

        priority_candidates = [
            item for item in candidates
            if self._candidate_category(item) in p.decision_categories
        ]
        if priority_candidates:
            for candidate in priority_candidates:
                if try_select(candidate, enforce_caps=True):
                    break

        for enforce_caps in (True, False):
            if len(selected) >= limit:
                break
            for candidate in candidates:
                if len(selected) >= limit:
                    break
                try_select(candidate, enforce_caps=enforce_caps)

        return selected
