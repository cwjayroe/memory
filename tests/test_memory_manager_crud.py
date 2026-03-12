from __future__ import annotations

import asyncio
import hashlib
import json


def _run_tool(module, name: str, arguments: dict):
    return asyncio.run(module.call_tool(name, arguments))[0].text


class _FakeMemory:
    def __init__(self):
        self.deleted: list[str] = []
        self.add_calls: list[dict] = []
        self.all_results: list[dict] = []

    def add(self, content: str, **kwargs):
        self.add_calls.append({"content": content, **kwargs})
        return {"results": [{"id": "new-id"}]}

    def get_all(self, **_kwargs):
        return {"results": list(self.all_results)}

    def delete(self, memory_id: str):
        self.deleted.append(memory_id)


# ---------------------------------------------------------------------------
# store_memory
# ---------------------------------------------------------------------------


def test_store_memory_rejects_empty_content(mcp_module):
    text = _run_tool(mcp_module, "store_memory", {"project_id": "automatic-discounts", "content": "   "})
    assert text == "Cannot store empty content."


def test_store_memory_auto_fingerprint_and_dedupes_existing(mcp_module, monkeypatch):
    memory = _FakeMemory()
    project_id = "automatic-discounts"
    repo = "customcheckout"
    source_path = "/repo/customcheckout/discounts.py"
    content = "decision body"
    source_kind = "summary"
    expected_fingerprint = hashlib.sha256(
        "||".join([project_id, repo, source_path, source_kind, content]).encode("utf-8")
    ).hexdigest()

    memory.all_results = [
        {"id": "old-id", "metadata": {"fingerprint": expected_fingerprint}},
        {"id": "ignore-id", "metadata": {"fingerprint": "other"}},
    ]

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text = _run_tool(
        mcp_module,
        "store_memory",
        {
            "project_id": project_id,
            "repo": repo,
            "source_path": source_path,
            "content": content,
        },
    )

    assert "Stored memory in project=automatic-discounts." in text
    assert "deleted_existing=1" in text
    assert memory.deleted == ["old-id"]
    assert memory.add_calls
    assert memory.add_calls[0]["metadata"]["fingerprint"] == expected_fingerprint


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------


def test_list_memories_filters_and_paginates(mcp_module, monkeypatch):
    memory = _FakeMemory()
    all_memories = [
        {
            "id": "newest",
            "memory": "newest matching memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/new.py",
                "updated_at": "2026-03-03T00:00:00+00:00",
                "tags": ["critical", "discounts"],
            },
        },
        {
            "id": "older",
            "memory": "older matching memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/old.py",
                "updated_at": "2026-03-01T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
        {
            "id": "filtered-out",
            "memory": "different repo",
            "metadata": {
                "repo": "other-repo",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/other/service.py",
                "updated_at": "2026-03-04T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
    ]

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)
    memory.all_results = list(all_memories)

    text = _run_tool(
        mcp_module,
        "list_memories",
        {
            "project_id": "automatic-discounts",
            "repo": "customcheckout",
            "category": "decision",
            "tag": "critical",
            "path_prefix": "/repo/customcheckout/service",
            "offset": 0,
            "limit": 1,
        },
    )

    assert "total_matches=2" in text
    assert "returned=1" in text
    assert "id=newest" in text
    assert "id=older" not in text


def test_list_memories_no_results_message(mcp_module, monkeypatch):
    memory = _FakeMemory()

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)
    memory.all_results = []

    text = _run_tool(
        mcp_module,
        "list_memories",
        {"project_id": "automatic-discounts", "offset": 0, "limit": 5},
    )

    assert "No memories found for project=automatic-discounts" in text


def test_list_memories_sorts_by_parsed_updated_at_with_fallback(mcp_module, monkeypatch):
    memory = _FakeMemory()
    all_memories = [
        {
            "id": "invalid",
            "memory": "missing recency signal",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/invalid.py",
                "updated_at": "not-a-date",
                "tags": ["critical"],
            },
        },
        {
            "id": "older",
            "memory": "older memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/old.py",
                "updated_at": "2026-03-01T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
        {
            "id": "newer",
            "memory": "newest memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/new.py",
                "updated_at": "2026-03-03T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
    ]

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)
    memory.all_results = list(all_memories)

    text = _run_tool(
        mcp_module,
        "list_memories",
        {"project_id": "automatic-discounts", "offset": 0, "limit": 10},
    )

    assert text.find("id=newer") < text.find("id=older")
    assert text.find("id=older") < text.find("id=invalid")


def test_list_memories_json_mode_and_full_text_respects_pagination(mcp_module, monkeypatch):
    memory = _FakeMemory()
    memory.all_results = [
        {
            "id": "newer",
            "memory": "newest memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/new.py",
                "updated_at": "2026-03-03T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
        {
            "id": "older",
            "memory": "older memory",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "source_kind": "summary",
                "source_path": "/repo/customcheckout/service/old.py",
                "updated_at": "2026-03-01T00:00:00+00:00",
                "tags": ["critical"],
            },
        },
    ]
    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text = _run_tool(
        mcp_module,
        "list_memories",
        {
            "project_id": "automatic-discounts",
            "offset": 0,
            "limit": 1,
            "response_format": "json",
            "include_full_text": True,
        },
    )
    payload = json.loads(text)

    assert payload["total_matches"] == 2
    assert payload["returned"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "newer"
    assert payload["items"][0]["full_text"] == "newest memory"


def test_get_memory_returns_untruncated_text_and_json(mcp_module, monkeypatch):
    memory = _FakeMemory()
    full_text = "Charge rule body " * 80
    memory.all_results = [
        {
            "id": "memory-1",
            "memory": full_text,
            "metadata": {
                "repo": "customcheckout",
                "category": "documentation",
                "source_kind": "doc",
                "source_path": "/repo/customcheckout/docs/rule.pdf",
                "updated_at": "2026-03-03T00:00:00+00:00",
                "tags": ["docs"],
            },
        }
    ]
    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text_output = _run_tool(
        mcp_module,
        "get_memory",
        {"project_id": "automatic-discounts", "memory_id": "memory-1"},
    )
    json_output = _run_tool(
        mcp_module,
        "get_memory",
        {
            "project_id": "automatic-discounts",
            "memory_id": "memory-1",
            "response_format": "json",
        },
    )
    payload = json.loads(json_output)

    assert "Memory for project=automatic-discounts memory_id=memory-1" in text_output
    assert full_text in text_output
    assert payload["item"]["id"] == "memory-1"
    assert payload["item"]["memory"] == full_text


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------


def test_delete_memory_by_id(mcp_module, monkeypatch):
    memory = _FakeMemory()
    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text = _run_tool(
        mcp_module,
        "delete_memory",
        {"project_id": "automatic-discounts", "memory_id": "abc-123"},
    )

    assert memory.deleted == ["abc-123"]
    assert "Deleted memory_id=abc-123" in text


def test_delete_memory_by_upsert_key(mcp_module, monkeypatch):
    memory = _FakeMemory()
    memory.all_results = [
        {"id": "d1", "metadata": {"upsert_key": "decision:one"}},
        {"id": "d2", "metadata": {"upsert_key": "decision:one"}},
        {"id": "keep", "metadata": {"upsert_key": "decision:two"}},
    ]

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text = _run_tool(
        mcp_module,
        "delete_memory",
        {"project_id": "automatic-discounts", "upsert_key": "decision:one"},
    )

    assert memory.deleted == ["d1", "d2"]
    assert "Deleted 2 memories with upsert_key=decision:one" in text


def test_delete_memory_requires_selector(mcp_module, monkeypatch):
    memory = _FakeMemory()
    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: memory)

    text = _run_tool(mcp_module, "delete_memory", {"project_id": "automatic-discounts"})
    assert text == "Provide memory_id or upsert_key."
