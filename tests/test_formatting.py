from __future__ import annotations

import json
from dataclasses import dataclass

from memory_core import formatting as fmt_module
from memory_core.formatting import ExcerptResult, ResultFormatter
from memory_core.memory_types import MemoryItem, MemoryMetadata


def _make_search_item(*, memory: str = "test content", project: str = "proj", repo: str = "repo1", category: str = "decision"):
    return {
        "id": "mem-1",
        "score": 0.85,
        "memory": memory,
        "_distance": 0.15,
        "_project_id": project,
        "_score_components": {
            "vector_component": 0.3,
            "lexical_component": 0.2,
            "metadata_component": 0.15,
            "recency_component": 0.1,
            "rerank_component": 0.25,
            "final_score": 0.85,
        },
        "metadata": {
            "project_id": project,
            "repo": repo,
            "category": category,
            "source_path": f"/repo/{repo}/service.py",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "tags": ["tag1"],
            "priority": "normal",
        },
    }


def _make_memory_item(**overrides) -> MemoryItem:
    defaults = {
        "id": "mem-1",
        "memory": "test body content",
        "metadata": {
            "repo": "customcheckout",
            "category": "decision",
            "source_kind": "summary",
            "source_path": "/repo/customcheckout/service.py",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "tags": ["tag1"],
        },
    }
    defaults.update(overrides)
    return MemoryItem.from_dict(defaults)


@dataclass
class _FakeRequest:
    query: str = "test query"
    response_format: str = "text"
    ranking_mode: str = "hybrid_weighted"
    token_budget: int = 1800
    debug: bool = False
    include_full_text: bool = False
    excerpt_chars: int = 420
    highlight: bool = False
    project_id: str = "proj"
    offset: int = 0
    limit: int = 10


# ---------------------------------------------------------------------------
# ExcerptResult
# ---------------------------------------------------------------------------


def test_excerpt_result_construction():
    er = ExcerptResult(text="hello", mode="full", start=0, end=5, truncated=False)
    assert er.text == "hello"
    assert er.mode == "full"
    assert er.truncated is False


# ---------------------------------------------------------------------------
# shorten
# ---------------------------------------------------------------------------


def test_shorten_returns_short_text_unchanged():
    f = ResultFormatter(shorten_limit=100)
    assert f.shorten("short text") == "short text"


def test_shorten_truncates_long_text():
    f = ResultFormatter(shorten_limit=20)
    result = f.shorten("a" * 50)
    assert len(result) == 20
    assert result.endswith("...")


def test_shorten_collapses_whitespace():
    f = ResultFormatter(shorten_limit=100)
    assert f.shorten("hello   world\n\tnewline") == "hello world newline"


def test_shorten_respects_excerpt_chars_override():
    f = ResultFormatter(shorten_limit=100)
    result = f.shorten("a" * 50, excerpt_chars=15)
    assert len(result) == 15
    assert result.endswith("...")


# ---------------------------------------------------------------------------
# build_excerpt
# ---------------------------------------------------------------------------


def test_build_excerpt_full_mode_for_short_text():
    f = ResultFormatter(shorten_limit=100)
    result = f.build_excerpt("short text")
    assert result.mode == "full"
    assert result.truncated is False
    assert result.text == "short text"


def test_build_excerpt_prefix_mode_for_long_text():
    f = ResultFormatter(shorten_limit=20)
    result = f.build_excerpt("a" * 50)
    assert result.mode == "prefix"
    assert result.truncated is True
    assert result.text.endswith("...")


def test_build_excerpt_matched_window_mode():
    f = ResultFormatter(shorten_limit=50)
    long_text = "prefix " * 20 + "MATCH_TARGET keyword here" + " suffix" * 20
    result = f.build_excerpt(long_text, query="MATCH_TARGET", prefer_query_match=True)
    assert result.mode == "matched-window"
    assert result.truncated is True
    assert "match_target" in result.text.lower()


def test_build_excerpt_no_match_falls_back_to_prefix():
    f = ResultFormatter(shorten_limit=30)
    result = f.build_excerpt("a" * 100, query="zzz_nonexistent", prefer_query_match=True)
    assert result.mode == "prefix"


# ---------------------------------------------------------------------------
# highlight_text
# ---------------------------------------------------------------------------


def test_highlight_text_wraps_tokens():
    f = ResultFormatter()
    result = f.highlight_text("the architecture decision was important", "architecture")
    assert "**architecture**" in result


def test_highlight_text_empty_query_returns_unchanged():
    f = ResultFormatter()
    original = "some text here"
    assert f.highlight_text(original, "") == original


def test_highlight_text_short_tokens_ignored():
    f = ResultFormatter()
    original = "a b c text"
    assert f.highlight_text(original, "a b") == original


# ---------------------------------------------------------------------------
# format_debug_components
# ---------------------------------------------------------------------------


def test_format_debug_components():
    f = ResultFormatter()
    item = _make_search_item()
    result = f.format_debug_components(item)
    assert "vector_component=0.3000" in result
    assert "final_score=0.8500" in result
    assert result.startswith("debug:")


def test_format_debug_components_empty():
    f = ResultFormatter()
    result = f.format_debug_components({})
    assert "vector_component=0.0000" in result


# ---------------------------------------------------------------------------
# format_search_row
# ---------------------------------------------------------------------------


def test_format_search_row_text_output():
    f = ResultFormatter()
    item = _make_search_item(memory="discount architecture body")
    result = f.format_search_row(
        1, item, query="discount", excerpt_chars=420,
        include_full_text=False, include_debug=False,
    )
    assert "[1]" in result
    assert "score=" in result
    assert "project=proj" in result
    assert "category=decision" in result


def test_format_search_row_with_debug():
    f = ResultFormatter()
    item = _make_search_item()
    result = f.format_search_row(
        1, item, query="test", excerpt_chars=420,
        include_full_text=False, include_debug=True,
    )
    assert "debug:" in result
    assert "excerpt_mode=" in result


def test_format_search_row_full_text():
    f = ResultFormatter()
    body = "full body text here"
    item = _make_search_item(memory=body)
    result = f.format_search_row(
        1, item, query="test", excerpt_chars=420,
        include_full_text=True,
    )
    assert "body=full" in result
    assert body in result


def test_format_search_row_highlight():
    f = ResultFormatter()
    item = _make_search_item(memory="architecture decision for checkout")
    result = f.format_search_row(
        1, item, query="architecture", excerpt_chars=420,
        include_full_text=False, highlight=True,
    )
    assert "**architecture**" in result


# ---------------------------------------------------------------------------
# format_search_payload — text and JSON
# ---------------------------------------------------------------------------


def test_format_search_payload_text_single_project():
    f = ResultFormatter()
    items = [_make_search_item()]
    req = _FakeRequest(query="test", debug=False)
    result = f.format_search_payload(
        packed=items, request=req, project_ids=["proj"],
        scope_source="explicit", rerank_used=False,
        inference_candidates=[],
    )
    assert "Found 1 memories for project=proj" in result


def test_format_search_payload_text_multi_project():
    f = ResultFormatter()
    items = [_make_search_item()]
    req = _FakeRequest(query="test")
    result = f.format_search_payload(
        packed=items, request=req, project_ids=["p1", "p2"],
        scope_source="explicit", rerank_used=False,
        inference_candidates=[],
    )
    assert "projects=p1,p2" in result


def test_format_search_payload_json_mode():
    f = ResultFormatter()
    items = [_make_search_item()]
    req = _FakeRequest(query="test", response_format="json")
    result = f.format_search_payload(
        packed=items, request=req, project_ids=["proj"],
        scope_source="explicit", rerank_used=False,
        inference_candidates=[],
    )
    payload = json.loads(result)
    assert payload["count"] == 1
    assert payload["query"] == "test"
    assert len(payload["items"]) == 1


def test_format_search_payload_inferred_empty_scope():
    f = ResultFormatter()
    req = _FakeRequest()
    result = f.format_search_payload(
        packed=[], request=req, project_ids=["proj"],
        scope_source="inferred-empty", rerank_used=False,
        inference_candidates=[],
    )
    assert "fallback-default" in result


def test_format_search_payload_debug_with_inference():
    f = ResultFormatter()
    req = _FakeRequest(debug=True)
    result = f.format_search_payload(
        packed=[], request=req, project_ids=["proj"],
        scope_source="explicit", rerank_used=False,
        inference_candidates=[("proj", 0.95)],
    )
    assert "inference_candidates=proj:0.95" in result


def test_format_search_payload_debug_reranker_error():
    f = ResultFormatter()
    req = _FakeRequest(debug=True)
    result = f.format_search_payload(
        packed=[], request=req, project_ids=["proj"],
        scope_source="explicit", rerank_used=False,
        inference_candidates=[],
        reranker_load_error="model not found",
    )
    assert "reranker_load_error=model not found" in result


# ---------------------------------------------------------------------------
# format_search_no_results
# ---------------------------------------------------------------------------


def test_format_search_no_results_text():
    f = ResultFormatter()
    req = _FakeRequest()
    result = f.format_search_no_results(
        request=req, project_ids=["proj"], scope_source="explicit",
    )
    assert result == "No matching context found."


def test_format_search_no_results_json():
    f = ResultFormatter()
    req = _FakeRequest(response_format="json")
    result = f.format_search_no_results(
        request=req, project_ids=["proj"], scope_source="explicit",
    )
    payload = json.loads(result)
    assert payload["count"] == 0
    assert payload["items"] == []
    assert payload["message"] == "No matching context found."


def test_format_search_no_results_inferred_empty():
    f = ResultFormatter()
    req = _FakeRequest(response_format="json")
    result = f.format_search_no_results(
        request=req, project_ids=["proj"], scope_source="inferred-empty",
    )
    payload = json.loads(result)
    assert payload["scope_source"] == "fallback-default"


# ---------------------------------------------------------------------------
# format_list_row
# ---------------------------------------------------------------------------


def test_format_list_row_text():
    f = ResultFormatter()
    item = _make_memory_item()
    result = f.format_list_row(item, excerpt_chars=420, include_full_text=False)
    assert "id=mem-1" in result
    assert "category=decision" in result
    assert "repo=customcheckout" in result


def test_format_list_row_full_text():
    f = ResultFormatter()
    item = _make_memory_item(memory="full body here")
    result = f.format_list_row(item, excerpt_chars=420, include_full_text=True)
    assert "body=full" in result
    assert "full body here" in result


# ---------------------------------------------------------------------------
# format_list_payload / format_list_no_results
# ---------------------------------------------------------------------------


def test_format_list_payload_text():
    f = ResultFormatter()
    req = _FakeRequest(project_id="proj")
    items = [_make_memory_item()]
    result = f.format_list_payload(request=req, page=items, total_matches=1)
    assert "Project memories for proj" in result
    assert "total_matches=1" in result


def test_format_list_payload_json():
    f = ResultFormatter()
    req = _FakeRequest(project_id="proj", response_format="json")
    items = [_make_memory_item()]
    result = f.format_list_payload(request=req, page=items, total_matches=1)
    payload = json.loads(result)
    assert payload["project_id"] == "proj"
    assert payload["returned"] == 1
    assert len(payload["items"]) == 1


def test_format_list_no_results_text():
    f = ResultFormatter()
    req = _FakeRequest(project_id="proj")
    result = f.format_list_no_results(request=req, total_matches=0)
    assert "No memories found for project=proj" in result


def test_format_list_no_results_json():
    f = ResultFormatter()
    req = _FakeRequest(project_id="proj", response_format="json")
    result = f.format_list_no_results(request=req, total_matches=0)
    payload = json.loads(result)
    assert payload["returned"] == 0
    assert payload["items"] == []


# ---------------------------------------------------------------------------
# format_memory_payload / format_memory_not_found
# ---------------------------------------------------------------------------


def test_format_memory_payload_text():
    f = ResultFormatter()
    item = _make_memory_item(memory="full memory body")
    result = f.format_memory_payload(
        project_id="proj", memory_item=item, response_format="text",
    )
    assert "Memory for project=proj memory_id=mem-1" in result
    assert "full memory body" in result


def test_format_memory_payload_json():
    f = ResultFormatter()
    item = _make_memory_item(memory="json body")
    result = f.format_memory_payload(
        project_id="proj", memory_item=item, response_format="json",
    )
    payload = json.loads(result)
    assert payload["project_id"] == "proj"
    assert payload["item"]["id"] == "mem-1"
    assert payload["item"]["memory"] == "json body"


def test_format_memory_not_found_text():
    f = ResultFormatter()
    result = f.format_memory_not_found(
        project_id="proj", memory_id="missing", response_format="text",
    )
    assert result == "Memory not found for project=proj memory_id=missing."


def test_format_memory_not_found_json():
    f = ResultFormatter()
    result = f.format_memory_not_found(
        project_id="proj", memory_id="missing", response_format="json",
    )
    payload = json.loads(result)
    assert payload["memory_id"] == "missing"
    assert payload["item"] is None
    assert payload["message"] == "Memory not found."
