from __future__ import annotations

import argparse


def test_manifest_v1_migrates_to_v2(manifest_module):
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


def test_context_plan_uses_repo_default_and_org_practices(ingest_module, manifest_module):
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


def test_validate_project_id(ingest_module):
    ingest_module.validate_project_id("checkout-tax")
    try:
        ingest_module.validate_project_id("CheckoutTax")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid project id to raise ValueError")


def test_policy_actions_preserve_decisions(ingest_module):
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


def test_project_init_uses_manifest_root_helper(ingest_module, tmp_path):
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
