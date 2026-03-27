from __future__ import annotations

import asyncio
import json

import mcp_server as mcp_module


def _run_tool(module, name: str, arguments: dict):
    return asyncio.run(module.call_tool(name, arguments))[0].text


def _packed_item(*, project: str = "automatic-discounts", repo: str = "customcheckout") -> dict:
    return {
        "score": 0.88,
        "memory": "Foundational architecture decision for discount flow",
        "_distance": 0.12,
        "_project_id": project,
        "metadata": {
            "project_id": project,
            "repo": repo,
            "category": "decision",
            "source_path": f"/repo/{repo}/service.py",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "tags": ["discounts", "decision"],
        },
    }


# ---------------------------------------------------------------------------
# Search caching
# ---------------------------------------------------------------------------


def test_search_context_uses_cache_when_not_debug(monkeypatch):
    run_calls = {"count": 0}

    async def fake_search(**_kwargs):
        run_calls["count"] += 1
        return ([_packed_item()], False)

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (["automatic-discounts"], "explicit", []),
    )
    monkeypatch.setattr(mcp_module.mem_manager, "search", fake_search)
    mcp_module.mem_manager._search_cache.clear()

    args = {"query": "discount architecture", "project_id": "automatic-discounts", "limit": 5}
    first = _run_tool(mcp_module, "search_context", args)
    second = _run_tool(mcp_module, "search_context", args)

    assert run_calls["count"] == 1
    assert first == second
    assert "Found 1 memories for project=automatic-discounts" in first


def test_search_context_debug_bypasses_cache(monkeypatch):
    run_calls = {"count": 0}

    async def fake_search(**_kwargs):
        run_calls["count"] += 1
        return ([_packed_item()], False)

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (["automatic-discounts"], "explicit", []),
    )
    monkeypatch.setattr(mcp_module.mem_manager, "search", fake_search)
    mcp_module.mem_manager._search_cache.clear()

    base_args = {"query": "discount architecture", "project_id": "automatic-discounts", "limit": 5}

    _run_tool(mcp_module, "search_context", base_args)
    debug_text = _run_tool(mcp_module, "search_context", {**base_args, "debug": True})
    _run_tool(mcp_module, "search_context", base_args)

    assert run_calls["count"] == 2
    assert "debug:" in debug_text


def test_search_cache_expired_entry_is_dropped():
    mcp_module.mem_manager._search_cache.clear()
    mcp_module.mem_manager._search_cache["k1"] = (0.0, "payload")

    assert mcp_module.mem_manager.search_cache_get("k1") is None
    assert "k1" not in mcp_module.mem_manager._search_cache


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------


def test_list_tools_schema_smoke():
    tools = asyncio.run(mcp_module.list_tools())
    tool_map = {tool.name: tool for tool in tools}

    assert {
        "search_context", "store_memory", "list_memories", "get_memory", "delete_memory",
        "ingest_repo", "ingest_file", "prune_memories", "init_project",
        "context_plan", "policy_run", "clear_memories",
    }.issubset(tool_map.keys())
    assert tool_map["search_context"].inputSchema["required"] == ["query"]
    assert tool_map["store_memory"].inputSchema["required"] == ["content"]
    assert tool_map["get_memory"].inputSchema["required"] == ["memory_id"]


def test_search_context_text_mode_uses_query_centered_excerpt(monkeypatch):
    run_calls = {"count": 0}
    long_prefix = "Scenario setup. " * 40
    matching_text = (
        "Charge date updates. If there are multiple queued charges for a subscription, "
        "the charge_date of a charge cannot be updated outside of the subscription cadence."
    )

    async def fake_search(**_kwargs):
        run_calls["count"] += 1
        return (
            [
                {
                    **_packed_item(),
                    "memory": f"{long_prefix}{matching_text} Tail context.",
                }
            ],
            False,
        )

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (["automatic-discounts"], "explicit", []),
    )
    monkeypatch.setattr(mcp_module.mem_manager, "search", fake_search)
    mcp_module.mem_manager._search_cache.clear()

    text = _run_tool(
        mcp_module,
        "search_context",
        {
            "query": "charge_date updated outside subscription cadence",
            "project_id": "automatic-discounts",
            "limit": 5,
        },
    )

    assert run_calls["count"] == 1
    assert "excerpt=matched-window" in text
    assert "charge_date of a charge cannot be updated outside of the subscription cadence" in text
    assert "Scenario setup." not in text


def test_search_context_json_mode_can_include_full_text(monkeypatch):
    async def fake_search(**_kwargs):
        return (
            [
                {
                    **_packed_item(),
                    "id": "memory-1",
                    "memory": "Exact full body for search result.",
                }
            ],
            False,
        )

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (["automatic-discounts"], "explicit", []),
    )
    monkeypatch.setattr(mcp_module.mem_manager, "search", fake_search)
    mcp_module.mem_manager._search_cache.clear()

    text = _run_tool(
        mcp_module,
        "search_context",
        {
            "query": "exact full body",
            "project_id": "automatic-discounts",
            "response_format": "json",
            "include_full_text": True,
        },
    )
    payload = json.loads(text)

    assert payload["count"] == 1
    assert payload["items"][0]["id"] == "memory-1"
    assert payload["items"][0]["full_text"] == "Exact full body for search result."
    assert payload["items"][0]["excerpt_info"]["mode"] in {"full", "matched-window", "prefix"}


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------


def test_update_memory_success(monkeypatch):
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "update_memory",
        lambda **kw: (True, "Updated memory project=proj new_id=new-1"),
    )
    result = _run_tool(mcp_module, "update_memory", {"memory_id": "mem-1", "body": "new body"})
    assert "Updated memory" in result


def test_update_memory_missing_memory_id(monkeypatch):
    result = _run_tool(mcp_module, "update_memory", {"body": "new body"})
    assert "memory_id is required." in result


def test_update_memory_no_fields(monkeypatch):
    result = _run_tool(mcp_module, "update_memory", {"memory_id": "mem-1"})
    assert "Provide at least one field to update" in result


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------


def test_find_similar_success(monkeypatch):
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "find_similar",
        lambda **kw: [{"id": "s1", "score": 0.9, "memory": "similar", "metadata": {"category": "decision"}}],
    )
    result = _run_tool(mcp_module, "find_similar", {"text": "test query"})
    assert "Found 1 similar" in result


def test_find_similar_missing_memory_id_and_text(monkeypatch):
    result = _run_tool(mcp_module, "find_similar", {})
    assert "Provide memory_id or text." in result


def test_find_similar_no_results(monkeypatch):
    monkeypatch.setattr(mcp_module.mem_manager, "find_similar", lambda **kw: [])
    result = _run_tool(mcp_module, "find_similar", {"text": "test query"})
    assert "No similar memories found." in result


# ---------------------------------------------------------------------------
# bulk_store
# ---------------------------------------------------------------------------


def test_bulk_store_success(monkeypatch):
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "bulk_store",
        lambda *a, **kw: [{"ok": True, "deleted_existing": 0, "ids": ["id1"]}],
    )
    result = _run_tool(mcp_module, "bulk_store", {"memories": [{"content": "test"}]})
    assert "ok=1" in result


def test_bulk_store_empty_memories(monkeypatch):
    result = _run_tool(mcp_module, "bulk_store", {"memories": []})
    assert "memories must be a non-empty list" in result


def test_bulk_store_non_list_memories(monkeypatch):
    result = _run_tool(mcp_module, "bulk_store", {"memories": "not a list"})
    assert "memories must be a non-empty list" in result


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_success(monkeypatch):
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "get_stats",
        lambda *a, **kw: {"project_id": "proj", "total_memories": 10},
    )
    result = _run_tool(mcp_module, "get_stats", {"project_id": "proj"})
    data = json.loads(result)
    assert data["total_memories"] == 10


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_success(monkeypatch):
    from memory_core import health as health_mod

    monkeypatch.setattr(
        health_mod,
        "run_health_check",
        lambda **kw: {"overall": "ok", "components": {}},
    )
    result = _run_tool(mcp_module, "health_check", {})
    data = json.loads(result)
    assert data["overall"] == "ok"


# ---------------------------------------------------------------------------
# move_memory
# ---------------------------------------------------------------------------


def test_move_memory_success(monkeypatch):
    from memory_core.memory_types import MemoryItem

    fake_item = MemoryItem.from_dict({"id": "m1", "memory": "body", "metadata": {"category": "decision"}})
    fake_target = type("FakeMemory", (), {"add": lambda *a, **kw: {"results": [{"id": "new-1", "memory": "body", "metadata": {"category": "decision"}}]}})()

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory_item", lambda *a, **kw: fake_item)
    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda *a, **kw: fake_target)
    monkeypatch.setattr(mcp_module.mem_manager, "delete_memory", lambda *a, **kw: None)

    result = _run_tool(mcp_module, "move_memory", {"memory_id": "m1", "target_project_id": "proj2"})
    assert "Moved memory" in result


def test_move_memory_missing_memory_id(monkeypatch):
    result = _run_tool(mcp_module, "move_memory", {"target_project_id": "proj2"})
    assert "memory_id is required." in result


def test_move_memory_missing_target_project_id(monkeypatch):
    result = _run_tool(mcp_module, "move_memory", {"memory_id": "m1"})
    assert "target_project_id is required." in result


# ---------------------------------------------------------------------------
# copy_scope
# ---------------------------------------------------------------------------


def test_copy_scope_dry_run(monkeypatch):
    from memory_core.memory_types import MemoryItem

    fake_item = MemoryItem.from_dict({"id": "m1", "memory": "body", "metadata": {"category": "decision"}})
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda *a, **kw: [fake_item])

    result = _run_tool(
        mcp_module,
        "copy_scope",
        {"from_project_id": "proj1", "to_project_id": "proj2", "dry_run": True},
    )
    assert "would copy 1" in result


def test_copy_scope_missing_from_to(monkeypatch):
    result = _run_tool(mcp_module, "copy_scope", {"from_project_id": "proj1"})
    assert "from_project_id and to_project_id are required." in result


def test_copy_scope_same_from_to(monkeypatch):
    result = _run_tool(mcp_module, "copy_scope", {"from_project_id": "proj", "to_project_id": "proj"})
    assert "from_project_id and to_project_id must differ." in result


# ---------------------------------------------------------------------------
# export_scope
# ---------------------------------------------------------------------------


def test_export_scope_success(monkeypatch):
    from memory_core.memory_types import MemoryItem

    fake_item = MemoryItem.from_dict({"id": "m1", "memory": "body", "metadata": {"category": "decision"}})
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda *a, **kw: [fake_item])

    result = _run_tool(mcp_module, "export_scope", {"project_id": "proj"})
    assert "Exported 1 memories" in result


# ---------------------------------------------------------------------------
# summarize_scope
# ---------------------------------------------------------------------------


def test_summarize_scope_success(monkeypatch):
    from memory_core.memory_types import MemoryItem

    from memory_core import summarizer as summarizer_mod

    fake_item = MemoryItem.from_dict({"id": "m1", "memory": "body", "metadata": {"category": "decision"}})
    monkeypatch.setattr(mcp_module.mem_manager, "get_all_items", lambda *a, **kw: [fake_item])
    monkeypatch.setattr(summarizer_mod, "generate_scope_summary", lambda **kw: "Test summary")

    result = _run_tool(mcp_module, "summarize_scope", {"project_id": "proj"})
    assert "Test summary" in result
