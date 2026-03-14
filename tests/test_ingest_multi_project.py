from __future__ import annotations

import argparse

import ingest as ingest_module
import manifest as manifest_module


def test_manifest_v1_migrates_to_v2():
    legacy = {
        "projects": {
            "automatic-discounts": {
                "repos": {
                    "customcheckout": {
                        "root": "/Users/willjayroe/Desktop/repos/customcheckout",
                        "include": ["**/*.py"],
                        "exclude": ["**/.git/**"],
                        "default_tags": ["checkout"],
                    }
                }
            }
        }
    }

    migrated = manifest_module._ensure_manifest_v2(legacy)
    assert migrated["version"] == 2
    assert "projects" in migrated
    assert "repos" in migrated
    assert "context_packs" in migrated
    assert "default_3_layer" in migrated["context_packs"]
    assert migrated["projects"]["automatic-discounts"]["repos"] == ["customcheckout"]
    assert migrated["repos"]["customcheckout"]["default_active_project"] == "automatic-discounts"


def test_context_plan_uses_repo_default_and_org_practices():
    manifest = {
        "version": 2,
        "defaults": {
            "ranking_mode": "hybrid_weighted_rerank",
            "token_budget": 1800,
            "limit": 6,
            "org_practice_projects": ["customcheckout-practices"],
        },
        "projects": {
            "checkout-tax": {"description": "Tax feature", "tags": ["tax"], "repos": ["customcheckout"]},
            "customcheckout-practices": {"description": "Practices", "tags": ["standards"], "repos": ["customcheckout"]},
        },
        "repos": {
            "customcheckout": {
                "root": "/Users/willjayroe/Desktop/repos/customcheckout",
                "default_active_project": "checkout-tax",
                "include": ["**/*.py"],
                "exclude": [],
                "default_tags": ["customcheckout"],
            }
        },
        "context_packs": {"default_3_layer": manifest_module.DEFAULT_CONTEXT_PACK},
    }

    plan = ingest_module.build_context_plan(
        manifest=manifest,
        repo="customcheckout",
        explicit_project=None,
        pack_name="default_3_layer",
    )

    assert plan["active_project"] == "checkout-tax"
    assert len(plan["layers"]) == 3
    layer_two_ids = plan["layers"][1]["payload"]["project_ids"]
    assert layer_two_ids == ["checkout-tax", "customcheckout-practices"]
    assert plan["layers"][2]["payload"]["repo"] == "customcheckout"


def test_context_plan_rejects_unknown_pack():
    manifest = {"version": 2, "projects": {}, "repos": {}, "context_packs": {}}

    try:
        ingest_module.build_context_plan(
            manifest=manifest,
            repo="customcheckout",
            explicit_project=None,
            pack_name="missing-pack",
        )
    except ValueError as exc:
        assert "Context pack not found" in str(exc)
    else:
        raise AssertionError("Expected missing context pack to raise ValueError")


def test_validate_project_id():
    ingest_module.validate_project_id("checkout-tax")
    try:
        ingest_module.validate_project_id("CheckoutTax")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid project id to raise ValueError")


def test_policy_actions_preserve_decisions():
    items = [
        {
            "id": "decision-1",
            "memory": "decision text",
            "metadata": {
                "repo": "customcheckout",
                "category": "decision",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "fingerprint": "fp-1",
            },
        },
        {
            "id": "code-old",
            "memory": "old code chunk",
            "metadata": {
                "repo": "customcheckout",
                "category": "code",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "fingerprint": "fp-2",
            },
        },
        {
            "id": "summary-1",
            "memory": "summary one",
            "metadata": {
                "repo": "customcheckout",
                "category": "summary",
                "updated_at": "2026-03-01T00:00:00+00:00",
                "upsert_key": "topic-1",
            },
        },
        {
            "id": "summary-2",
            "memory": "summary two",
            "metadata": {
                "repo": "customcheckout",
                "category": "summary",
                "updated_at": "2026-02-01T00:00:00+00:00",
                "upsert_key": "topic-1",
            },
        },
    ]

    policy = ingest_module.build_policy_actions(
        items=items,
        stale_days=45,
        summary_keep=1,
        repo="customcheckout",
    )

    assert "decision-1" not in policy["delete_ids"]
    assert "summary-2" in policy["delete_ids"]


def test_resolve_repo_config_rejects_repo_outside_project():
    manifest = {
        "version": 2,
        "projects": {
            "checkout-tax": {"repos": ["customcheckout"]},
        },
        "repos": {
            "shopify-discount-import-dapr": {
                "root": ".",
                "include": ["**/*.py"],
                "exclude": [],
                "default_tags": ["sync"],
            }
        },
    }

    try:
        manifest_module.resolve_repo_config(
            manifest=manifest,
            project_id="checkout-tax",
            repo="shopify-discount-import-dapr",
            root_override=None,
            include_override=None,
            exclude_override=None,
        )
    except ValueError as exc:
        assert "checkout-tax" in str(exc)
        assert "shopify-discount-import-dapr" in str(exc)
    else:
        raise AssertionError("Expected undeclared repo to raise ValueError")


def test_project_init_uses_manifest_root_helper(tmp_path):
    manifest_path = tmp_path / "projects.yaml"
    args = argparse.Namespace(
        project="checkout-tax",
        repos="new-unmapped-repo",
        description="",
        tags=None,
        set_repo_defaults=False,
        manifest=str(manifest_path),
    )

    ingest_module.cmd_project_init(args)
    manifest = ingest_module.read_manifest(manifest_path)
    repo_entry = manifest["repos"]["new-unmapped-repo"]
    assert "root" in repo_entry


def test_ensure_manifest_v2_already_v2():
    v2 = {
        "version": 2,
        "projects": {"proj": {"repos": ["repo1"]}},
        "repos": {"repo1": {"root": "/tmp/repo1"}},
        "context_packs": {"default_3_layer": manifest_module.DEFAULT_CONTEXT_PACK},
    }
    result = manifest_module._ensure_manifest_v2(v2)
    assert result["version"] == 2
    assert result["projects"] == v2["projects"]
    assert result["repos"] == v2["repos"]


def test_validate_project_id_empty_and_special_chars():
    import pytest
    with pytest.raises(ValueError):
        manifest_module.validate_project_id("")
    with pytest.raises(ValueError):
        manifest_module.validate_project_id("Has Spaces")
    with pytest.raises(ValueError):
        manifest_module.validate_project_id("UPPERCASE")
    # Valid ones should not raise (kebab-case only, no underscores)
    manifest_module.validate_project_id("valid-project-123")
    manifest_module.validate_project_id("myproject")


def test_write_manifest_round_trip(tmp_path):
    manifest_path = tmp_path / "test_manifest.yaml"
    original = {
        "version": 2,
        "projects": {"test-proj": {"description": "test", "tags": ["t1"], "repos": ["r1"]}},
        "repos": {"r1": {"root": "/tmp/r1", "include": ["*.py"], "exclude": [], "default_tags": ["r1"]}},
        "context_packs": {},
    }
    manifest_module.write_manifest(manifest_path, original)
    loaded = manifest_module.read_manifest(manifest_path)
    assert loaded["version"] == 2
    assert loaded["projects"]["test-proj"]["description"] == "test"
    assert loaded["repos"]["r1"]["root"] == "/tmp/r1"


def test_guess_repo_root():
    # Use a repo name that exists under /Users/willjayroe/Desktop/repos (e.g. memories)
    root = manifest_module.guess_repo_root("memories")
    assert isinstance(root, str)
    assert "memories" in root


def test_resolve_repo_config_with_overrides():
    manifest = {
        "version": 2,
        "projects": {"proj": {"repos": ["myrepo"]}},
        "repos": {
            "myrepo": {
                "root": "/tmp/myrepo",
                "include": ["*.py"],
                "exclude": ["*.pyc"],
                "default_tags": ["tag1"],
            }
        },
    }
    config = manifest_module.resolve_repo_config(
        manifest=manifest,
        project_id="proj",
        repo="myrepo",
        root_override="/custom/root",
        include_override=["*.md"],
        exclude_override=["*.tmp"],
    )
    from pathlib import Path
    assert config.root == Path("/custom/root")
    assert config.include == ["*.md"]
    assert config.exclude == ["*.tmp"]


def test_build_context_plan_with_empty_projects():
    manifest = {
        "version": 2,
        "defaults": {},
        "projects": {},
        "repos": {
            "myrepo": {
                "root": "/tmp/myrepo",
                "include": ["*.py"],
                "exclude": [],
                "default_tags": [],
            }
        },
        "context_packs": {"default_3_layer": manifest_module.DEFAULT_CONTEXT_PACK},
    }
    plan = manifest_module.build_context_plan(
        manifest=manifest,
        repo="myrepo",
        explicit_project=None,
        pack_name="default_3_layer",
    )
    # Should still produce layers, even with no projects
    assert "layers" in plan
    assert len(plan["layers"]) > 0


def test_build_policy_actions_all_decisions_preserved():
    items = [
        {"id": "d1", "memory": "decision one", "metadata": {"category": "decision", "updated_at": "2024-01-01T00:00:00+00:00"}},
        {"id": "d2", "memory": "decision two", "metadata": {"category": "decision", "updated_at": "2024-06-01T00:00:00+00:00"}},
    ]
    policy = ingest_module.build_policy_actions(items=items, stale_days=45, summary_keep=5)
    assert "d1" not in policy["delete_ids"]
    assert "d2" not in policy["delete_ids"]
