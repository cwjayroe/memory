from __future__ import annotations

import asyncio

import mcp_server as mcp_module


def _memory_item(*, score: float, project: str, repo: str, category: str, text: str):
    return {
        "score": score,
        "memory": text,
        "metadata": {
            "project_id": project,
            "repo": repo,
            "category": category,
            "source_path": f"/repo/{repo}/{category}.py",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "tags": ["automatic-discounts", repo],
        },
    }


def _run(module, args):
    return asyncio.run(module.call_tool("search_context", args))[0].text


def test_unknown_tool_returns_expected_error():
    text = asyncio.run(mcp_module.call_tool("not_a_tool", {}))[0].text
    assert text == "Unknown tool: not_a_tool"


def test_single_project_backward_compatible(monkeypatch):
    async def fake_collect(_projects, _query, _candidate_limit):
        return {
            "automatic-discounts": [
                _memory_item(
                    score=0.25,
                    project="automatic-discounts",
                    repo="customcheckout",
                    category="decision",
                    text="Automatic discount service is injected into regen service.",
                )
            ]
        }

    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine.reranker, "apply", lambda *_args, **_kwargs: False)
    mcp_module.mem_manager._search_cache.clear()

    text = _run(
        mcp_module,
        {
            "query": "automatic discount architecture",
            "project_id": "automatic-discounts",
            "limit": 5,
        },
    )

    assert "Found 1 memories for project=automatic-discounts" in text
    assert "project=automatic-discounts" in text
    assert "distance=" in text


def test_multi_project_and_repo_filter(monkeypatch):
    async def fake_collect(_projects, _query, _candidate_limit):
        return {
            "automatic-discounts": [
                _memory_item(
                    score=0.35,
                    project="automatic-discounts",
                    repo="customcheckout",
                    category="code",
                    text="customcheckout automatic discount flow",
                ),
                _memory_item(
                    score=0.10,
                    project="automatic-discounts",
                    repo="other-repo",
                    category="summary",
                    text="other repo should be filtered out",
                ),
            ],
            "customcheckout-practices": [
                _memory_item(
                    score=0.40,
                    project="customcheckout-practices",
                    repo="customcheckout",
                    category="architecture",
                    text="customcheckout best practices for services and dependency injection",
                )
            ],
        }

    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine.reranker, "apply", lambda *_args, **_kwargs: False)
    mcp_module.mem_manager._search_cache.clear()

    text = _run(
        mcp_module,
        {
            "query": "customcheckout automatic discounts best practices",
            "project_ids": ["automatic-discounts", "customcheckout-practices"],
            "repo": "customcheckout",
            "ranking_mode": "hybrid_weighted",
            "token_budget": 1800,
            "limit": 10,
        },
    )

    assert "projects=automatic-discounts,customcheckout-practices" in text
    assert "repo=customcheckout" in text
    assert "other-repo" not in text
    assert "project=customcheckout-practices" in text


def test_debug_includes_score_components(monkeypatch):
    async def fake_collect(_projects, _query, _candidate_limit):
        return {
            "automatic-discounts": [
                _memory_item(
                    score=0.30,
                    project="automatic-discounts",
                    repo="customcheckout",
                    category="decision",
                    text="decision content for debug output coverage",
                )
            ]
        }

    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine.reranker, "apply", lambda *_args, **_kwargs: False)
    mcp_module.mem_manager._search_cache.clear()

    text = _run(
        mcp_module,
        {
            "query": "decision debug components",
            "project_id": "automatic-discounts",
            "debug": True,
            "ranking_mode": "hybrid_weighted",
            "limit": 5,
        },
    )

    assert "debug: vector_component=" in text
    assert "final_score=" in text


def test_inferred_scope_without_explicit_project_ids(monkeypatch):
    async def fake_collect(_projects, _query, _candidate_limit):
        return {
            "automatic-discounts": [
                _memory_item(
                    score=0.22,
                    project="automatic-discounts",
                    repo="product-docs",
                    category="documentation",
                    text="Automatic discounts PRD summary and constraints",
                )
            ],
            "customcheckout-practices": [
                _memory_item(
                    score=0.40,
                    project="customcheckout-practices",
                    repo="customcheckout",
                    category="architecture",
                    text="Service layering standards",
                )
            ],
        }

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (
            ["automatic-discounts", "customcheckout-practices"],
            "inferred",
            [("automatic-discounts", 7.5), ("customcheckout-practices", 4.2)],
        ),
    )
    monkeypatch.setattr(mcp_module.mem_manager, "_warm_memory_handles", lambda _project_ids: None)
    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine.reranker, "apply", lambda *_args, **_kwargs: False)
    mcp_module.mem_manager._search_cache.clear()

    text = _run(
        mcp_module,
        {
            "query": "show me automatic discounts product doc requirements",
            "ranking_mode": "hybrid_weighted",
            "limit": 5,
        },
    )

    assert "scope_source=inferred" in text
    assert "resolved_projects=automatic-discounts,customcheckout-practices" in text
    assert "project=automatic-discounts" in text


def test_inferred_no_hit_triggers_fallback_retry(monkeypatch):
    calls: list[list[str]] = []

    async def fake_collect(_projects, _query, _candidate_limit):
        calls.append(list(_projects))
        if _projects == ["automatic-discounts"]:
            return {"automatic-discounts": []}
        if _projects == ["customcheckout-practices", "org-practices"]:
            return {
                "customcheckout-practices": [
                    _memory_item(
                        score=0.31,
                        project="customcheckout-practices",
                        repo="customcheckout",
                        category="summary",
                        text="Fallback retry memory from default project scope",
                    )
                ],
                "org-practices": [],
            }
        return {}

    monkeypatch.setattr(
        mcp_module,
        "_resolve_search_scope",
        lambda _request, _config: (
            ["automatic-discounts"],
            "inferred",
            [("automatic-discounts", 6.0)],
        ),
    )
    monkeypatch.setattr(mcp_module, "DEFAULT_PROJECT_ID", "customcheckout-practices")
    monkeypatch.setattr(
        mcp_module,
        "_resolve_org_practice_projects",
        lambda _max_projects, _manifest_path: ["org-practices"],
    )
    monkeypatch.setattr(mcp_module.mem_manager, "_warm_memory_handles", lambda _project_ids: None)
    monkeypatch.setattr(mcp_module.mem_manager, "_collect_project_searches", fake_collect)
    monkeypatch.setattr(mcp_module.scoring_engine.reranker, "apply", lambda *_args, **_kwargs: False)
    mcp_module.mem_manager._search_cache.clear()

    text = _run(
        mcp_module,
        {
            "query": "automatic discounts product doc",
            "ranking_mode": "hybrid_weighted",
            "limit": 5,
        },
    )

    assert calls[0] == ["automatic-discounts"]
    assert calls[1] == ["customcheckout-practices", "org-practices"]
    assert "scope_source=fallback-retry" in text
    assert "resolved_projects=customcheckout-practices,org-practices" in text
