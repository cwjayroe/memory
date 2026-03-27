from __future__ import annotations

from memory_core import tagging as tagging_module


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


def test_tokenize_basic():
    tokens = tagging_module._tokenize("Hello World architecture decision")
    assert "hello" in tokens
    assert "world" in tokens
    assert "architecture" in tokens


def test_tokenize_filters_short_and_uppercase():
    tokens = tagging_module._tokenize("A BC def GHI")
    assert "def" in tokens
    assert "ghi" in tokens
    assert "a" not in tokens  # single char filtered by regex
    assert "bc" not in tokens  # two chars filtered by regex


def test_tokenize_empty():
    assert tagging_module._tokenize("") == []
    assert tagging_module._tokenize("12 34") == []  # digits-only don't start with letter


# ---------------------------------------------------------------------------
# _extract_candidate_tags
# ---------------------------------------------------------------------------


def test_extract_candidate_tags_filters_stop_words():
    body = "the function should return the value and handle the error"
    candidates = tagging_module._extract_candidate_tags(body, [], max_candidates=10)
    assert "the" not in candidates
    assert "function" not in candidates  # in stop words
    assert "handle" in candidates or "error" in candidates


def test_extract_candidate_tags_boosts_existing_vocab():
    body = "architecture decision for database migration workflow"
    existing = ["architecture", "migration"]
    candidates = tagging_module._extract_candidate_tags(body, existing, max_candidates=5)
    architecture_idx = candidates.index("architecture") if "architecture" in candidates else 999
    migration_idx = candidates.index("migration") if "migration" in candidates else 999
    assert architecture_idx < 5 or migration_idx < 5


def test_extract_candidate_tags_empty_body():
    assert tagging_module._extract_candidate_tags("", [], max_candidates=5) == []


def test_extract_candidate_tags_respects_max_candidates():
    body = " ".join([f"term{i}" for i in range(50)])
    result = tagging_module._extract_candidate_tags(body, [], max_candidates=3)
    assert len(result) <= 3


# ---------------------------------------------------------------------------
# suggest_tags
# ---------------------------------------------------------------------------


def test_suggest_tags_normal_body():
    body = "This architecture decision affects the database migration workflow and deployment pipeline"
    tags = tagging_module.suggest_tags(body)
    assert isinstance(tags, list)
    assert len(tags) > 0
    assert len(tags) <= 5


def test_suggest_tags_empty_body():
    assert tagging_module.suggest_tags("") == []


def test_suggest_tags_respects_max_suggestions():
    body = "architecture database migration workflow deployment pipeline orchestration kubernetes"
    tags = tagging_module.suggest_tags(body, max_suggestions=2)
    assert len(tags) <= 2


def test_suggest_tags_with_existing_vocab():
    body = "architecture decision for database migration"
    tags = tagging_module.suggest_tags(body, existing_tag_vocab=["architecture", "migration"])
    assert isinstance(tags, list)
