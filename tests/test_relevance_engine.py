from __future__ import annotations

from collections import Counter

import scoring as scoring_module


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


def test_metadata_component_weights():
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


def test_dedupe_prefers_lower_distance():
    engine = scoring_module.ScoringEngine()
    item1 = _make_item(score=0.9, category="code", upsert_key="discounts:auto")
    item2 = _make_item(score=0.2, category="summary", upsert_key="discounts:auto")
    deduped = engine.dedupe_candidates([item1, item2])
    assert len(deduped) == 1
    assert deduped[0]["score"] == 0.2


def test_pack_candidates_respects_budget_and_diversity():
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


def test_distance_similarity():
    assert scoring_module.distance_similarity(0.0) == 1.0
    assert scoring_module.distance_similarity(1.0) == 0.5
    assert 0.0 < scoring_module.distance_similarity(100.0) < 0.02


def test_normalize_score_values():
    assert scoring_module.normalize_score_values([]) == []
    assert scoring_module.normalize_score_values([5.0]) == [1.0]
    assert scoring_module.normalize_score_values([0.0, 0.0]) == [0.0, 0.0]
    result = scoring_module.normalize_score_values([1.0, 3.0, 5.0])
    assert result == [0.0, 0.5, 1.0]


def test_estimate_tokens():
    assert scoring_module.estimate_tokens("") == 0
    assert scoring_module.estimate_tokens("word") == 1
    assert scoring_module.estimate_tokens("a" * 100) == 25


def test_dedupe_key_upsert_key():
    item = _make_item(score=0.5, category="decision", upsert_key="my-key")
    key = scoring_module.dedupe_key(item)
    assert key == "upsert::my-key"


def test_dedupe_key_fingerprint():
    item = _make_item(score=0.5, category="decision")
    item["metadata"]["fingerprint"] = "fp123"
    key = scoring_module.dedupe_key(item)
    assert key.startswith("fingerprint::")
    assert "fp123" in key


def test_dedupe_key_fallback_hash():
    item = _make_item(score=0.5, category="decision")
    key = scoring_module.dedupe_key(item)
    assert key.startswith("fallback::")


def test_recency_component():
    from datetime import datetime, timezone

    now = datetime(2026, 3, 13, tzinfo=timezone.utc)
    recent = _make_item(score=0.5, category="decision")
    recent["metadata"]["updated_at"] = "2026-03-12T00:00:00+00:00"
    old = _make_item(score=0.5, category="code")
    old["metadata"]["updated_at"] = "2025-01-01T00:00:00+00:00"
    missing = _make_item(score=0.5, category="summary")
    del missing["metadata"]["updated_at"]

    recent_score = scoring_module.recency_component(recent, now)
    old_score = scoring_module.recency_component(old, now)
    missing_score = scoring_module.recency_component(missing, now)

    assert recent_score > old_score
    assert missing_score == 0.2


def test_lexical_components():
    # Use 3+ documents so BM25 IDF is non-zero (with 2 docs, IDF for terms in 1 doc is 0).
    items = [
        _make_item(score=0.5, category="decision"),
        _make_item(score=0.5, category="code"),
        _make_item(score=0.5, category="summary"),
    ]
    items[0]["memory"] = "discount architecture checkout flow"
    items[1]["memory"] = "unrelated database migration"
    items[2]["memory"] = "other summary content"
    scores = scoring_module.lexical_components("discount architecture", items)
    assert len(scores) == 3
    assert scores[0] > scores[1]  # first item is more relevant (has query terms)
    assert scores[0] > scores[2]


def test_lexical_components_empty_query():
    items = [_make_item(score=0.5, category="decision")]
    scores = scoring_module.lexical_components("", items)
    assert scores == [0.0]


def test_score_candidates_attaches_components(monkeypatch):
    engine = scoring_module.ScoringEngine()
    items = [
        _make_item(score=0.3, category="decision"),
        _make_item(score=0.8, category="code", repo="other"),
    ]
    # Monkeypatch BM25 to avoid needing rank_bm25
    monkeypatch.setattr(scoring_module, "BM25Okapi", None)

    result = engine.score_candidates(
        "discount architecture",
        items,
        repo="customcheckout",
        path_prefix=None,
        tags=[],
        categories=["decision"],
        ranking_mode="hybrid_weighted",
        rerank_top_n=10,
    )
    assert len(result) == 2
    for item in result:
        assert "_score_components" in item
        assert "_pre_rerank_score" in item
        assert "_distance" in item


def test_finalize_scores_sorts_by_final():
    engine = scoring_module.ScoringEngine()
    items = [
        {
            "score": 0.1,
            "memory": "low",
            "_score_components": {
                "vector_component": 0.1,
                "lexical_component": 0.1,
                "metadata_component": 0.1,
                "recency_component": 0.1,
                "rerank_component": 0.1,
            },
        },
        {
            "score": 0.9,
            "memory": "high",
            "_score_components": {
                "vector_component": 0.9,
                "lexical_component": 0.9,
                "metadata_component": 0.9,
                "recency_component": 0.9,
                "rerank_component": 0.9,
            },
        },
    ]
    result = engine.finalize_scores(items)
    assert result[0]["memory"] == "high"
    assert result[1]["memory"] == "low"
    assert result[0]["_score_components"]["final_score"] > result[1]["_score_components"]["final_score"]
