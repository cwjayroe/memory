from __future__ import annotations

import argparse
from memory_core import memory_types as contracts_module


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


def test_update_memory_request_parsing():
    req = contracts_module.UpdateMemoryRequest.from_arguments(
        {"memory_id": " mem-1 ", "body": "new body", "category": "architecture", "tags": "tag1,tag2", "priority": "high"},
        default_project_id="default-proj",
    )
    assert req.memory_id == "mem-1"
    assert req.body == "new body"
    assert req.category == "architecture"
    assert req.tags == ["tag1", "tag2"]
    assert req.priority == "high"
    assert req.project_id == "default-proj"


def test_update_memory_request_no_tags():
    req = contracts_module.UpdateMemoryRequest.from_arguments(
        {"memory_id": "m1", "body": "text"},
        default_project_id="proj",
    )
    assert req.tags is None  # None means "don't update tags"


def test_update_memory_request_invalid_priority():
    req = contracts_module.UpdateMemoryRequest.from_arguments(
        {"memory_id": "m1", "priority": "invalid"},
        default_project_id="proj",
    )
    assert req.priority is None


def test_find_similar_request_parsing():
    req = contracts_module.FindSimilarRequest.from_arguments(
        {"text": "test query", "threshold": "0.5", "limit": "20", "response_format": "json"},
        default_project_id="proj",
    )
    assert req.text == "test query"
    assert req.threshold == 0.5
    assert req.limit == 20
    assert req.response_format == "json"


def test_find_similar_request_clamps():
    req = contracts_module.FindSimilarRequest.from_arguments(
        {"text": "q", "threshold": "2.0", "limit": "999"},
        default_project_id="proj",
    )
    assert req.threshold == 1.0  # clamped to max
    assert req.limit == 50  # clamped to max


def test_note_request_from_namespace():
    req = contracts_module.NoteRequest.from_namespace(
        argparse.Namespace(
            project="proj", text=" note text ", repo="myrepo",
            source_path="/path/file.py", source_kind="decision", category="decision", tags="tag1,tag2",
        )
    )
    assert req.text == "note text"
    assert req.repo == "myrepo"
    assert req.tags == ["tag1", "tag2"]


def test_prune_request_from_namespace():
    req = contracts_module.PruneRequest.from_namespace(
        argparse.Namespace(project="proj", repo="myrepo", path_prefix="/path", by="fingerprint")
    )
    assert req.project == "proj"
    assert req.repo == "myrepo"
    assert req.by == "fingerprint"


def test_clear_request_from_namespace():
    req = contracts_module.ClearRequest.from_namespace(
        argparse.Namespace(project="proj")
    )
    assert req.project == "proj"


def test_context_plan_request_from_namespace():
    req = contracts_module.ContextPlanRequest.from_namespace(
        argparse.Namespace(repo="myrepo", project="proj", pack="default_3_layer", manifest="/tmp/projects.yaml")
    )
    assert req.repo == "myrepo"
    assert req.project == "proj"
    assert req.pack == "default_3_layer"
    assert str(req.manifest_path) == "/tmp/projects.yaml"


def test_policy_run_request_from_namespace():
    req = contracts_module.PolicyRunRequest.from_namespace(
        argparse.Namespace(project="proj", mode="dry-run", stale_days=30, summary_keep=3, repo="myrepo", path_prefix="/path")
    )
    assert req.project == "proj"
    assert req.mode == "dry-run"
    assert req.stale_days == 30
    assert req.summary_keep == 3
    assert req.repo == "myrepo"


def test_policy_run_request_clamps():
    req = contracts_module.PolicyRunRequest.from_namespace(
        argparse.Namespace(project="proj", mode="apply", stale_days=-5, summary_keep=-1, repo=None, path_prefix=None)
    )
    assert req.stale_days == 0
    assert req.summary_keep == 1


def test_memory_metadata_from_dict_and_as_dict():
    md = contracts_module.MemoryMetadata.from_dict({
        "project_id": "proj", "repo": "myrepo", "category": "decision",
        "source_kind": "summary", "tags": "tag1,tag2", "priority": "high",
        "custom_field": "custom_value",
    })
    assert md.project_id == "proj"
    assert md.repo == "myrepo"
    assert md.priority == "high"
    assert md.tags == ["tag1", "tag2"]
    assert md.extra == {"custom_field": "custom_value"}

    as_dict = md.as_dict()
    assert as_dict["project_id"] == "proj"
    assert as_dict["priority"] == "high"
    assert as_dict["custom_field"] == "custom_value"


def test_memory_metadata_from_dict_defaults():
    md = contracts_module.MemoryMetadata.from_dict(None)
    assert md.project_id is None
    assert md.tags == []
    assert md.priority == "normal"
    assert md.extra == {}


def test_memory_metadata_invalid_priority():
    md = contracts_module.MemoryMetadata.from_dict({"priority": "critical"})
    assert md.priority == "normal"


def test_ingest_list_request_from_namespace():
    req = contracts_module.IngestListRequest.from_namespace(
        argparse.Namespace(project="proj", repo="myrepo", category="decision", tag="tag1", path_prefix="/path", offset=0, limit=20)
    )
    assert req.project == "proj"
    assert req.repo == "myrepo"
    assert req.limit == 20
