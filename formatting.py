"""Output formatting for project-memory search and list results."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from memory_types import MemoryItem
from scoring import get_metadata


@dataclass(frozen=True)
class ExcerptResult:
    text: str
    mode: str
    start: int
    end: int
    truncated: bool


class ResultFormatter:
    """Formats search results, list output, and debug diagnostics."""

    def __init__(self, *, shorten_limit: int = 420):
        self._shorten_limit = shorten_limit

    def _normalize_excerpt_chars(self, excerpt_chars: int | None = None) -> int:
        if isinstance(excerpt_chars, int) and excerpt_chars > 0:
            return excerpt_chars
        return self._shorten_limit

    def _clean_text(self, text: str) -> str:
        return " ".join(text.split())

    def shorten(self, text: str, *, excerpt_chars: int | None = None) -> str:
        clean = self._clean_text(text)
        limit = self._normalize_excerpt_chars(excerpt_chars)
        if len(clean) <= limit:
            return clean
        return f"{clean[: limit - 3]}..."

    def _query_tokens(self, query: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9_./:-]+", query.lower())
        unique: list[str] = []
        for token in tokens:
            if len(token) < 3:
                continue
            if token not in unique:
                unique.append(token)
        return unique

    def _snap_start(self, text: str, index: int) -> int:
        if index <= 0:
            return 0
        while index > 0 and not text[index - 1].isspace():
            index -= 1
        return index

    def _snap_end(self, text: str, index: int) -> int:
        if index >= len(text):
            return len(text)
        while index < len(text) and not text[index].isspace():
            index += 1
        return index

    def _snap_to_sentence_start(self, text: str, index: int, fallback_floor: int) -> int:
        window_start = max(0, index - 200)
        candidates = [
            text.rfind(". ", window_start, index),
            text.rfind("! ", window_start, index),
            text.rfind("? ", window_start, index),
        ]
        sentence_break = max(candidates)
        if sentence_break >= fallback_floor:
            return sentence_break + 2
        return index

    def _find_match_window(self, text: str, query: str, limit: int) -> tuple[int, int] | None:
        if not text or len(text) <= limit:
            return None

        lower_text = text.lower()
        tokens = self._query_tokens(query)
        if not tokens:
            return None

        best_score: tuple[int, int, int] | None = None
        best_window: tuple[int, int] | None = None
        half = max(limit // 2, 1)

        for token in tokens:
            for match in re.finditer(re.escape(token), lower_text):
                lead_context = min(max(limit // 6, 40), half)
                start = max(0, match.start() - lead_context)
                start = self._snap_to_sentence_start(text, match.start(), start)
                end = min(len(text), start + limit)
                start = self._snap_start(text, start)
                end = self._snap_end(text, end)
                window_text = lower_text[start:end]
                token_hits = sum(1 for item in tokens if item in window_text)
                score = (token_hits, len(token), -match.start())
                if best_score is None or score > best_score:
                    best_score = score
                    best_window = (start, end)

        return best_window

    def build_excerpt(
        self,
        text: str,
        *,
        excerpt_chars: int | None = None,
        query: str | None = None,
        prefer_query_match: bool = False,
    ) -> ExcerptResult:
        clean = self._clean_text(text)
        limit = self._normalize_excerpt_chars(excerpt_chars)
        if len(clean) <= limit:
            return ExcerptResult(
                text=clean,
                mode="full",
                start=0,
                end=len(clean),
                truncated=False,
            )

        window: tuple[int, int] | None = None
        mode = "prefix"
        if prefer_query_match and query:
            window = self._find_match_window(clean, query, limit)
            if window is not None:
                mode = "matched-window"

        if window is None:
            window = (0, min(limit, len(clean)))

        start, end = window
        snippet = clean[start:end]
        if start > 0:
            snippet = f"...{snippet}"
        if end < len(clean):
            snippet = f"{snippet}..."

        return ExcerptResult(
            text=snippet,
            mode=mode,
            start=start,
            end=end,
            truncated=True,
        )

    def format_debug_components(self, memory_item: dict[str, Any]) -> str:
        components = memory_item.get("_score_components", {})
        return (
            "debug: "
            f"vector_component={float(components.get('vector_component', 0.0)):.4f} "
            f"lexical_component={float(components.get('lexical_component', 0.0)):.4f} "
            f"metadata_component={float(components.get('metadata_component', 0.0)):.4f} "
            f"recency_component={float(components.get('recency_component', 0.0)):.4f} "
            f"rerank_component={float(components.get('rerank_component', 0.0)):.4f} "
            f"final_score={float(components.get('final_score', 0.0)):.4f}"
        )

    def _search_item_payload(
        self,
        memory_item: dict[str, Any],
        *,
        query: str,
        excerpt_chars: int,
        include_full_text: bool,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        metadata = get_metadata(memory_item)
        project = memory_item.get("_project_id") or metadata.get("project_id", "unknown-project")
        body = str(memory_item.get("memory", ""))
        excerpt = self.build_excerpt(
            body,
            excerpt_chars=excerpt_chars,
            query=query,
            prefer_query_match=True,
        )
        payload = {
            "id": memory_item.get("id"),
            "score": memory_item.get("score"),
            "distance": memory_item.get("_distance"),
            "project_id": project,
            "metadata": metadata,
            "excerpt": excerpt.text,
            "excerpt_info": {
                "mode": excerpt.mode,
                "start": excerpt.start,
                "end": excerpt.end,
                "truncated": excerpt.truncated,
            },
        }
        if include_full_text:
            payload["full_text"] = body
        if include_debug:
            payload["score_components"] = memory_item.get("_score_components", {})
        return payload

    def _list_item_payload(
        self,
        memory_item: MemoryItem,
        *,
        excerpt_chars: int,
        include_full_text: bool,
    ) -> dict[str, Any]:
        excerpt = self.build_excerpt(
            memory_item.memory,
            excerpt_chars=excerpt_chars,
            prefer_query_match=False,
        )
        payload = {
            "id": memory_item.id,
            "metadata": memory_item.metadata.as_dict(),
            "excerpt": excerpt.text,
            "excerpt_info": {
                "mode": excerpt.mode,
                "start": excerpt.start,
                "end": excerpt.end,
                "truncated": excerpt.truncated,
            },
        }
        if include_full_text:
            payload["full_text"] = memory_item.memory
        return payload

    def format_search_row(
        self,
        index: int,
        memory_item: dict[str, Any],
        *,
        query: str,
        excerpt_chars: int,
        include_full_text: bool,
        include_debug: bool = False,
    ) -> str:
        item_payload = self._search_item_payload(
            memory_item,
            query=query,
            excerpt_chars=excerpt_chars,
            include_full_text=include_full_text,
            include_debug=include_debug,
        )
        metadata = item_payload["metadata"]
        score = item_payload.get("score")
        score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "n/a"
        distance = item_payload.get("distance")
        distance_text = f"{float(distance):.4f}" if isinstance(distance, (int, float)) else "n/a"
        excerpt_info = item_payload["excerpt_info"]
        content_label = "body" if include_full_text else "excerpt"
        content_mode = "full" if include_full_text else excerpt_info["mode"]
        lines = [
            (
                f"[{index}] score={score_text} distance={distance_text} "
                f"project={item_payload['project_id']} "
                f"category={metadata.get('category', 'general')} "
                f"repo={metadata.get('repo', 'unknown-repo')}"
            ),
            f"path={metadata.get('source_path', 'unknown-path')}",
            (
                f"{content_label}={content_mode} "
                f"chars={excerpt_info['start']}:{excerpt_info['end']} "
                f"truncated={str(excerpt_info['truncated']).lower()}"
            ),
            item_payload["full_text"] if include_full_text else item_payload["excerpt"],
        ]
        if include_debug:
            lines.append(self.format_debug_components(memory_item))
            lines.append(
                "debug: "
                f"excerpt_mode={excerpt_info['mode']} "
                f"excerpt_range={excerpt_info['start']}:{excerpt_info['end']}"
            )
        return "\n".join(lines)

    def format_list_row(
        self,
        memory_item: MemoryItem,
        *,
        excerpt_chars: int,
        include_full_text: bool,
    ) -> str:
        metadata = memory_item.metadata
        tags = metadata.tags
        item_payload = self._list_item_payload(
            memory_item,
            excerpt_chars=excerpt_chars,
            include_full_text=include_full_text,
        )
        excerpt_info = item_payload["excerpt_info"]
        content_label = "body" if include_full_text else "snippet"
        content_mode = "full" if include_full_text else excerpt_info["mode"]
        return (
            f"id={memory_item.id} category={metadata.category or 'general'} "
            f"repo={metadata.repo or 'n/a'} source_kind={metadata.source_kind or 'summary'}\n"
            f"path={metadata.source_path or 'n/a'} updated_at={metadata.updated_at or 'n/a'} "
            f"tags={','.join(tags) if tags else 'n/a'}\n"
            f"{content_label}={content_mode} chars={excerpt_info['start']}:{excerpt_info['end']} "
            f"truncated={str(excerpt_info['truncated']).lower()}\n"
            f"{item_payload['full_text'] if include_full_text else item_payload['excerpt']}"
        )

    def format_search_payload(
        self,
        *,
        packed: list[dict[str, Any]],
        request: Any,
        project_ids: list[str],
        scope_source: str,
        rerank_used: bool,
        inference_candidates: list[tuple[str, float]],
        reranker_load_error: str | None = None,
    ) -> str:
        if request.response_format == "json":
            return self.format_search_payload_json(
                packed=packed,
                request=request,
                project_ids=project_ids,
                scope_source=scope_source,
                rerank_used=rerank_used,
                inference_candidates=inference_candidates,
                reranker_load_error=reranker_load_error,
            )

        display_scope_source = (
            "fallback-default" if scope_source == "inferred-empty" else scope_source
        )
        resolved_projects = ",".join(project_ids)
        if len(project_ids) == 1:
            rows = [
                (
                    f"Found {len(packed)} memories for project={project_ids[0]} "
                    f"(scope_source={display_scope_source}, resolved_projects={resolved_projects}, "
                    f"ranking_mode={request.ranking_mode}, rerank_used={rerank_used}, token_budget={request.token_budget}):"
                )
            ]
        else:
            rows = [
                (
                    f"Found {len(packed)} memories for projects={','.join(project_ids)} "
                    f"(scope_source={display_scope_source}, resolved_projects={resolved_projects}, "
                    f"ranking_mode={request.ranking_mode}, rerank_used={rerank_used}, token_budget={request.token_budget}):"
                )
            ]
        for index, item in enumerate(packed, start=1):
            rows.append(
                self.format_search_row(
                    index,
                    item,
                    query=request.query,
                    excerpt_chars=request.excerpt_chars,
                    include_full_text=request.include_full_text,
                    include_debug=request.debug,
                )
            )
        if request.debug:
            if inference_candidates:
                formatted = ",".join(
                    f"{project}:{score:.2f}" for project, score in inference_candidates
                )
            else:
                formatted = "n/a"
            rows.append(f"debug: inference_candidates={formatted}")
        if request.debug and reranker_load_error:
            rows.append(f"debug: reranker_load_error={reranker_load_error}")
        return "\n\n".join(rows)

    def format_search_payload_json(
        self,
        *,
        packed: list[dict[str, Any]],
        request: Any,
        project_ids: list[str],
        scope_source: str,
        rerank_used: bool,
        inference_candidates: list[tuple[str, float]],
        reranker_load_error: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "query": request.query,
            "scope_source": "fallback-default" if scope_source == "inferred-empty" else scope_source,
            "resolved_projects": project_ids,
            "ranking_mode": request.ranking_mode,
            "rerank_used": rerank_used,
            "token_budget": request.token_budget,
            "count": len(packed),
            "items": [
                self._search_item_payload(
                    item,
                    query=request.query,
                    excerpt_chars=request.excerpt_chars,
                    include_full_text=request.include_full_text,
                    include_debug=request.debug,
                )
                for item in packed
            ],
        }
        if request.debug:
            payload["debug"] = {
                "inference_candidates": [
                    {"project_id": project_id, "score": score}
                    for project_id, score in inference_candidates
                ],
            }
            if reranker_load_error:
                payload["debug"]["reranker_load_error"] = reranker_load_error
        return json.dumps(payload, indent=2, sort_keys=False)

    def format_search_no_results(
        self,
        *,
        request: Any,
        project_ids: list[str],
        scope_source: str,
    ) -> str:
        if request.response_format == "json":
            return json.dumps(
                {
                    "query": request.query,
                    "scope_source": "fallback-default" if scope_source == "inferred-empty" else scope_source,
                    "resolved_projects": project_ids,
                    "message": "No matching context found.",
                    "count": 0,
                    "items": [],
                },
                indent=2,
                sort_keys=False,
            )
        return "No matching context found."

    def format_list_payload(
        self,
        *,
        request: Any,
        page: list[MemoryItem],
        total_matches: int,
    ) -> str:
        if request.response_format == "json":
            return json.dumps(
                {
                    "project_id": request.project_id,
                    "total_matches": total_matches,
                    "offset": request.offset,
                    "limit": request.limit,
                    "returned": len(page),
                    "items": [
                        self._list_item_payload(
                            item,
                            excerpt_chars=request.excerpt_chars,
                            include_full_text=request.include_full_text,
                        )
                        for item in page
                    ],
                },
                indent=2,
                sort_keys=False,
            )

        response_lines = [
            (
                f"Project memories for {request.project_id}: total_matches={total_matches} "
                f"offset={request.offset} limit={request.limit} returned={len(page)}"
            )
        ]
        for item in page:
            response_lines.append(
                self.format_list_row(
                    item,
                    excerpt_chars=request.excerpt_chars,
                    include_full_text=request.include_full_text,
                )
            )
        return "\n\n".join(response_lines)

    def format_list_no_results(self, *, request: Any, total_matches: int) -> str:
        if request.response_format == "json":
            return json.dumps(
                {
                    "project_id": request.project_id,
                    "total_matches": total_matches,
                    "offset": request.offset,
                    "limit": request.limit,
                    "returned": 0,
                    "items": [],
                },
                indent=2,
                sort_keys=False,
            )
        return (
            f"No memories found for project={request.project_id} "
            f"(total_matches={total_matches}, offset={request.offset}, limit={request.limit})."
        )

    def format_memory_payload(
        self,
        *,
        project_id: str,
        memory_item: MemoryItem,
        response_format: str,
    ) -> str:
        metadata = memory_item.metadata
        if response_format == "json":
            return json.dumps(
                {
                    "project_id": project_id,
                    "item": {
                        "id": memory_item.id,
                        "memory": memory_item.memory,
                        "metadata": metadata.as_dict(),
                    },
                },
                indent=2,
                sort_keys=False,
            )

        return (
            f"Memory for project={project_id} memory_id={memory_item.id}\n"
            f"id={memory_item.id} category={metadata.category or 'general'} "
            f"repo={metadata.repo or 'n/a'} source_kind={metadata.source_kind or 'summary'}\n"
            f"path={metadata.source_path or 'n/a'} updated_at={metadata.updated_at or 'n/a'} "
            f"tags={','.join(metadata.tags) if metadata.tags else 'n/a'}\n"
            f"{memory_item.memory}"
        )

    def format_memory_not_found(
        self,
        *,
        project_id: str,
        memory_id: str,
        response_format: str,
    ) -> str:
        if response_format == "json":
            return json.dumps(
                {
                    "project_id": project_id,
                    "memory_id": memory_id,
                    "message": "Memory not found.",
                    "item": None,
                },
                indent=2,
                sort_keys=False,
            )
        return f"Memory not found for project={project_id} memory_id={memory_id}."
