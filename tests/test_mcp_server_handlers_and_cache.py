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
        "ingest_repo", "ingest_file", "prune_memories", "init_project", "clear_memories",
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
