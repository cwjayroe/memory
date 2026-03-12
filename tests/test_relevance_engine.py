from __future__ import annotations

from collections import Counter


def _make_item(*, score: float, category: str, repo: str = "customcheckout", project_id: str = "automatic-discounts", upsert_key: str | None = None):
    metadata = {
        "project_id": project_id,
        "repo": repo,
        "source_path": f"/tmp/{repo}/{category}.py",
        "category": category,
        "updated_at": "2026-03-01T00:00:00+00:00",
        "tags": ["automatic-discounts", category],
    }
    if upsert_key:
        metadata["upsert_key"] = upsert_key
    return {
        "score": score,
        "memory": f"{category} memory content for {repo}",
        "metadata": metadata,
        "_project_id": project_id,
    }


def test_metadata_component_weights(scoring_module):
    engine = scoring_module.ScoringEngine()
    item = _make_item(score=0.2, category="decision")
    score = engine._metadata_component(
        item,
        repo="customcheckout",
        path_prefix="/tmp/customcheckout",
        tags=["automatic-discounts"],
        categories=["decision"],
    )
    assert score == 1.0


def test_dedupe_prefers_lower_distance(scoring_module):
    engine = scoring_module.ScoringEngine()
    item1 = _make_item(score=0.9, category="code", upsert_key="discounts:auto")
    item2 = _make_item(score=0.2, category="summary", upsert_key="discounts:auto")
    deduped = engine.dedupe_candidates([item1, item2])
    assert len(deduped) == 1
    assert deduped[0]["score"] == 0.2


def test_pack_candidates_respects_budget_and_diversity(scoring_module):
    engine = scoring_module.ScoringEngine()
    candidates = [
        _make_item(score=0.95, category="summary"),
        _make_item(score=0.92, category="code"),
        _make_item(score=0.90, category="decision"),
        _make_item(score=0.89, category="code", repo="shopify-discount-import-dapr"),
        _make_item(score=0.88, category="architecture"),
    ]
    for item in candidates:
        item["memory"] = item["memory"] + (" x" * 120)

    selected = engine.pack_candidates(candidates, limit=4, token_budget=220)
    assert selected
    assert len(selected) <= 4
    assert any(item["metadata"]["category"] in {"decision", "architecture"} for item in selected)

    total_tokens = sum(scoring_module.estimate_tokens(item["memory"]) for item in selected)
    assert total_tokens <= 220

    repo_counts = Counter((item["_project_id"], item["metadata"]["repo"]) for item in selected)
    assert all(count <= engine.packing.max_repo_results for count in repo_counts.values())
