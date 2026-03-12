from __future__ import annotations

import asyncio

import mcp_server as mcp_module


def test_collect_project_searches_handles_timeout_and_exceptions(monkeypatch):
    async def fake_search(project_id: str, _query: str, _candidate_limit: int):
        if project_id == "slow":
            await asyncio.sleep(0.05)
            return [{"id": "slow"}]
        if project_id == "boom":
            raise RuntimeError("search failed")
        return [{"id": "fast"}]

    monkeypatch.setattr(mcp_module.mem_manager, "_search_project_candidates", fake_search)
    from dataclasses import replace
    monkeypatch.setattr(
        mcp_module.mem_manager,
        "_config",
        replace(mcp_module.mem_manager._config, global_timeout_seconds=0.01),
    )

    results = asyncio.run(
        mcp_module.mem_manager._collect_project_searches(["fast", "boom", "slow"], "discount", 10)
    )

    assert results["fast"] == [{"id": "fast"}]
    assert results["boom"] == []
    assert results["slow"] == []


def test_search_project_sync_returns_memoryitem_instances(monkeypatch):
    class _SearchMemory:
        def search(self, **_kwargs):
            return {
                "results": [
                    {
                        "id": "mem-1",
                        "memory": "typed conversion",
                        "metadata": {"repo": "customcheckout", "category": "decision"},
                    },
                    "bad-entry",
                ]
            }

    monkeypatch.setattr(mcp_module.mem_manager, "get_memory", lambda _project_id, **_kw: _SearchMemory())

    results = mcp_module.mem_manager._search_project_sync("automatic-discounts", "discount", 10)

    assert len(results) == 1
    assert results[0].id == "mem-1"
    assert results[0].metadata.repo == "customcheckout"


def test_run_search_pass_filters_typed_items_and_backfills_project_id(monkeypatch):
    kept_item = {
        "id": "k1",
        "memory": "kept item",
        "metadata": {
            "repo": "customcheckout",
            "category": "decision",
            "source_path": "/repo/customcheckout/flow.py",
            "tags": ["critical"],
        },
    }
    dropped_item = {
        "id": "d1",
        "memory": "drop by repo filter",
        "metadata": {
            "repo": "other-repo",
            "category": "decision",
            "source_path": "/repo/other/flow.py",
            "tags": ["critical"],
        },
    }

    captured: list[dict] = []

    async def fake_collect(_project_ids, _query, _candidate_limit):
        return {"automatic-discounts": [kept_item, dropped_item]}

    def fake_score_candidates(_query, candidates, **_kwargs):
        captured.extend(candidates)
        return candidates

    monkeypatch.setattr(mcp_module.mem_manager, "_warm_memory_handles", lambda _project_ids: None)
    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(mcp_module.scoring_engine, "finalize_scores", lambda candidates: candidates)
    monkeypatch.setattr(mcp_module.scoring_engine, "pack_candidates", lambda candidates, **_kwargs: candidates)

    request = mcp_module.SearchContextRequest.from_arguments(
        {
            "query": "discount architecture",
            "project_ids": ["automatic-discounts"],
            "repo": "customcheckout",
            "path_prefix": "/repo/customcheckout",
            "tags": ["critical"],
            "categories": ["decision"],
            "ranking_mode": "hybrid_weighted",
            "rerank_top_n": 10,
            "limit": 10,
            "token_budget": 2000,
            "candidate_pool": 30,
        },
        policy=mcp_module.SEARCH_PARSE_POLICY,
    )
    packed, rerank_used = asyncio.run(mcp_module.mem_manager.search(request=request))

    assert rerank_used is False
    assert len(packed) == 1
    assert len(captured) == 1
    assert captured[0]["id"] == "k1"
    assert captured[0]["_project_id"] == "automatic-discounts"
    assert captured[0]["metadata"]["project_id"] == "automatic-discounts"
