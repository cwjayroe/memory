from __future__ import annotations

from dataclasses import dataclass, field

import helpers as helpers_module
import memory_types as dataclasses_module


# ---------------------------------------------------------------------------
# Minimal stand-ins for MemoryItem-like objects used by _find_ids
# ---------------------------------------------------------------------------


@dataclass
class _Meta:
    upsert_key: str | None = None
    fingerprint: str | None = None


@dataclass
class _FakeItem:
    id: str | None
    metadata: _Meta = field(default_factory=_Meta)


# ---------------------------------------------------------------------------
# normalize_tags / normalize_strings
# ---------------------------------------------------------------------------


def test_normalize_tags_handles_str_list_and_none():
    assert helpers_module.normalize_tags(None) == []
    assert helpers_module.normalize_tags("a, b, c") == ["a", "b", "c"]
    assert helpers_module.normalize_tags(["x", " y ", ""]) == ["x", "y"]
    assert helpers_module.normalize_tags(42) == []
    assert helpers_module.normalize_tags("") == []
    assert helpers_module.normalize_tags("  single  ") == ["single"]


def test_normalize_strings_handles_str_list_and_none():
    assert helpers_module.normalize_strings(None) == []
    assert helpers_module.normalize_strings("a,b,c") == ["a", "b", "c"]
    assert helpers_module.normalize_strings(["x", " y ", ""]) == ["x", "y"]
    assert helpers_module.normalize_strings(0) == []


# ---------------------------------------------------------------------------
# dedupe_keep_order
# ---------------------------------------------------------------------------


def test_dedupe_keep_order_preserves_first_occurrence():
    assert helpers_module.dedupe_keep_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
    assert helpers_module.dedupe_keep_order(["", "a", ""]) == ["a"]
    assert helpers_module.dedupe_keep_order([]) == []
    assert helpers_module.dedupe_keep_order(["x"]) == ["x"]


# ---------------------------------------------------------------------------
# _find_ids — upsert_key vs fingerprint matching
# ---------------------------------------------------------------------------


def test_find_ids_by_upsert_key():
    items = [
        _FakeItem("id-1", _Meta(upsert_key="k1")),
        _FakeItem("id-2", _Meta(upsert_key="k2")),
        _FakeItem("id-3", _Meta()),
    ]
    assert helpers_module._find_ids(items, upsert_key="k1") == ["id-1"]
    assert helpers_module._find_ids(items, upsert_key="k2") == ["id-2"]
    assert helpers_module._find_ids(items, upsert_key="missing") == []


def test_find_ids_by_fingerprint():
    items = [
        _FakeItem("id-1", _Meta(fingerprint="fp1")),
        _FakeItem("id-2", _Meta(fingerprint="fp2")),
        _FakeItem("id-3", _Meta()),
    ]
    assert helpers_module._find_ids(items, fingerprint="fp1") == ["id-1"]
    assert helpers_module._find_ids(items, fingerprint="missing") == []


def test_find_ids_skips_non_string_ids():
    items = [
        _FakeItem(None, _Meta(upsert_key="k1")),
        _FakeItem(123, _Meta(upsert_key="k1")),  # type: ignore[arg-type]
        _FakeItem("real-id", _Meta(upsert_key="k1")),
    ]
    assert helpers_module._find_ids(items, upsert_key="k1") == ["real-id"]


# ---------------------------------------------------------------------------
# _matches_filters — all filter dimensions
# ---------------------------------------------------------------------------


def test_matches_filters_repo():
    item = {"id": "x", "memory": "m", "metadata": {"repo": "customcheckout", "tags": []}}
    assert helpers_module._matches_filters(item, repo="customcheckout") is True
    assert helpers_module._matches_filters(item, repo="other") is False
    assert helpers_module._matches_filters(item) is True  # no filters → always passes


def test_matches_filters_path_prefix():
    item = {"id": "x", "memory": "m", "metadata": {"source_path": "/repo/cc/service.py", "tags": []}}
    assert helpers_module._matches_filters(item, path_prefix="/repo/cc") is True
    assert helpers_module._matches_filters(item, path_prefix="/repo/other") is False
    no_path = {"id": "x", "memory": "m", "metadata": {"tags": []}}
    assert helpers_module._matches_filters(no_path, path_prefix="/repo/cc") is False


def test_matches_filters_categories():
    item = {"id": "x", "memory": "m", "metadata": {"category": "decision", "tags": []}}
    assert helpers_module._matches_filters(item, categories=["decision", "summary"]) is True
    assert helpers_module._matches_filters(item, categories=["summary"]) is False


def test_matches_filters_tags():
    item = {"id": "x", "memory": "m", "metadata": {"tags": ["a", "b"]}}
    assert helpers_module._matches_filters(item, tags=["b"]) is True
    assert helpers_module._matches_filters(item, tags=["c"]) is False
    assert helpers_module._matches_filters(item, tags=[]) is True  # empty → no filter


# ---------------------------------------------------------------------------
# parse_datetime
# ---------------------------------------------------------------------------


def test_parse_datetime_handles_formats_and_errors():
    assert helpers_module.parse_datetime("2026-03-01T00:00:00Z") is not None
    assert helpers_module.parse_datetime("2026-03-01T00:00:00+00:00") is not None
    assert helpers_module.parse_datetime("not-a-date") is None
    assert helpers_module.parse_datetime(None) is None
    assert helpers_module.parse_datetime("") is None
    assert helpers_module.parse_datetime(42) is None


def test_parse_datetime_attaches_utc_to_naive():
    dt = helpers_module.parse_datetime("2026-03-01T12:00:00")
    assert dt is not None
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _is_transient_memory_init_error
# ---------------------------------------------------------------------------


def test_is_transient_memory_init_error():
    assert helpers_module._is_transient_memory_init_error(RuntimeError("RustBindingsAPI failed"))
    assert helpers_module._is_transient_memory_init_error(Exception("no attribute 'bindings'"))
    assert helpers_module._is_transient_memory_init_error(Exception("Could not connect to tenant"))
    assert not helpers_module._is_transient_memory_init_error(ValueError("unrelated error"))
    assert not helpers_module._is_transient_memory_init_error(Exception(""))



# ---------------------------------------------------------------------------
# results_from_payload
# ---------------------------------------------------------------------------


def test_results_from_payload_filters_non_dicts():
    payload = {"results": [{"id": "a", "memory": "x"}, "bad", None, {"id": "b", "memory": "y"}]}
    results = helpers_module.results_from_payload(payload)
    assert len(results) == 2
    assert results[0].id == "a"
    assert results[1].id == "b"


def test_results_from_payload_handles_non_dict_input():
    assert helpers_module.results_from_payload("not-a-dict") == []
    assert helpers_module.results_from_payload(None) == []
    assert helpers_module.results_from_payload({"no_results_key": []}) == []


# ---------------------------------------------------------------------------
# _build_search_cache_key — determinism
# ---------------------------------------------------------------------------


def test_build_search_cache_key_is_deterministic():
    policy = dataclasses_module.SearchContextParsePolicy(max_projects_per_query=5)
    req = dataclasses_module.SearchContextRequest.from_arguments(
        {"query": "discount architecture", "project_id": "automatic-discounts"},
        policy=policy,
    )
    k1 = helpers_module._build_search_cache_key(req, ["automatic-discounts"])
    k2 = helpers_module._build_search_cache_key(req, ["automatic-discounts"])
    assert k1 == k2


def test_build_search_cache_key_differs_by_query_and_projects():
    policy = dataclasses_module.SearchContextParsePolicy(max_projects_per_query=5)
    req1 = dataclasses_module.SearchContextRequest.from_arguments(
        {"query": "discounts", "project_id": "p1"},
        policy=policy,
    )
    req2 = dataclasses_module.SearchContextRequest.from_arguments(
        {"query": "architecture", "project_id": "p1"},
        policy=policy,
    )
    k1 = helpers_module._build_search_cache_key(req1, ["p1"])
    k2 = helpers_module._build_search_cache_key(req2, ["p1"])
    k3 = helpers_module._build_search_cache_key(req1, ["p2"])
    assert k1 != k2  # different query
    assert k1 != k3  # different project_ids list
