from __future__ import annotations

import argparse
import memory_types as contracts_module


def test_search_context_request_parsing_and_clamps():
    policy = contracts_module.SearchContextParsePolicy(
        max_projects_per_query=10,
        default_limit=8,
        max_limit=20,
        default_ranking_mode="hybrid_weighted_rerank",
        allowed_ranking_modes=frozenset({"hybrid_weighted_rerank", "hybrid_weighted"}),
        default_token_budget=1800,
        min_token_budget=600,
        max_token_budget=4000,
        default_rerank_top_n=40,
        max_candidate_pool=200,
    )
    request = contracts_module.SearchContextRequest.from_arguments(
        {
            "query": "  discount architecture  ",
            "project_ids": "automatic-discounts,customcheckout-practices,automatic-discounts",
            "repo": "customcheckout",
            "tags": "discounts,checkout",
            "categories": "decision,architecture",
            "limit": 999,
            "ranking_mode": "invalid-mode",
            "token_budget": 99999,
            "candidate_pool": 5,
            "rerank_top_n": 999,
            "debug": "yes",
        },
        policy=policy,
    )

    assert request.query == "discount architecture"
    assert request.project_ids == ["automatic-discounts", "customcheckout-practices"]
    assert request.limit == 20
    assert request.ranking_mode == "hybrid_weighted_rerank"
    assert request.token_budget == 4000
    assert request.candidate_pool == 10
    assert request.rerank_top_n == 200
    assert request.debug is True
    assert request.response_format == "text"
    assert request.include_full_text is False
    assert request.excerpt_chars == 420


def test_store_list_delete_request_parsing_defaults():
    store = contracts_module.StoreMemoryRequest.from_arguments(
        {"content": "  keep this  ", "source_kind": "decision", "project_id": ""},
        default_project_id="customcheckout-practices",
    )
    assert store.project_id == "customcheckout-practices"
    assert store.content == "keep this"
    assert store.category == "decision"

    listed = contracts_module.ListMemoriesRequest.from_arguments(
        {"offset": -5, "limit": 999},
        default_project_id="customcheckout-practices",
        default_limit=20,
        max_limit=100,
    )
    assert listed.offset == 0
    assert listed.limit == 100
    assert listed.response_format == "text"
    assert listed.include_full_text is False
    assert listed.excerpt_chars == 420

    deleted = contracts_module.DeleteMemoryRequest.from_arguments(
        {"upsert_key": "decision:auto-discounts"},
        default_project_id="customcheckout-practices",
    )
    assert deleted.project_id == "customcheckout-practices"
    assert deleted.memory_id is None
    assert deleted.upsert_key == "decision:auto-discounts"

    fetched = contracts_module.GetMemoryRequest.from_arguments(
        {"memory_id": " mem-1 ", "project_id": "", "response_format": "json"},
        default_project_id="customcheckout-practices",
    )
    assert fetched.project_id == "customcheckout-practices"
    assert fetched.memory_id == "mem-1"
    assert fetched.response_format == "json"


def test_ingest_request_models_from_namespace():
    repo_req = contracts_module.RepoIngestRequest.from_namespace(
        argparse.Namespace(
            project="automatic-discounts",
            repo="customcheckout",
            root=None,
            mode="mixed",
            include=None,
            exclude=None,
            tags="discounts,checkout",
            manifest="/tmp/projects.yaml",
        )
    )
    assert repo_req.tags == ["discounts", "checkout"]
    assert str(repo_req.manifest_path) == "/tmp/projects.yaml"

    file_req = contracts_module.FileIngestRequest.from_namespace(
        argparse.Namespace(
            project="automatic-discounts",
            repo="customcheckout",
            path="/tmp/service.py",
            mode="mixed",
            tags="discounts,checkout",
            manifest="/tmp/file-projects.yaml",
        )
    )
    assert file_req.tags == ["discounts", "checkout"]
    assert str(file_req.manifest_path) == "/tmp/file-projects.yaml"

    init_req = contracts_module.ProjectInitRequest.from_namespace(
        argparse.Namespace(
            project="checkout-tax",
            repos="customcheckout,shopify-discount-import-dapr",
            description="tax project",
            tags="tax,checkout",
            set_repo_defaults=True,
            manifest="/tmp/projects.yaml",
        )
    )
    assert init_req.repos == ["customcheckout", "shopify-discount-import-dapr"]
    assert init_req.tags == ["tax", "checkout"]
    assert init_req.set_repo_defaults is True
