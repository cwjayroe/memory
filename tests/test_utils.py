from __future__ import annotations

import utils as utils_module


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------


def test_safe_int_valid():
    assert utils_module.safe_int(42, 0) == 42
    assert utils_module.safe_int("10", 0) == 10
    assert utils_module.safe_int(3.9, 0) == 3


def test_safe_int_invalid():
    assert utils_module.safe_int(None, 5) == 5
    assert utils_module.safe_int("abc", 5) == 5
    assert utils_module.safe_int([], 5) == 5


# ---------------------------------------------------------------------------
# optional_str
# ---------------------------------------------------------------------------


def test_optional_str_valid():
    assert utils_module.optional_str("hello") == "hello"
    assert utils_module.optional_str("  padded  ") == "padded"


def test_optional_str_empty_or_nonstring():
    assert utils_module.optional_str("") is None
    assert utils_module.optional_str("   ") is None
    assert utils_module.optional_str(None) is None
    assert utils_module.optional_str(42) is None
    assert utils_module.optional_str([]) is None


# ---------------------------------------------------------------------------
# as_bool
# ---------------------------------------------------------------------------


def test_as_bool_booleans():
    assert utils_module.as_bool(True) is True
    assert utils_module.as_bool(False) is False


def test_as_bool_truthy_strings():
    for val in ("1", "true", "True", "TRUE", "yes", "Yes", "y", "Y", "on", "ON"):
        assert utils_module.as_bool(val) is True, f"Expected True for {val!r}"


def test_as_bool_falsy_strings():
    for val in ("0", "false", "False", "no", "off", "", "random"):
        assert utils_module.as_bool(val) is False, f"Expected False for {val!r}"


def test_as_bool_nonstring():
    assert utils_module.as_bool(1) is True
    assert utils_module.as_bool(0) is False


# ---------------------------------------------------------------------------
# normalize_tags
# ---------------------------------------------------------------------------


def test_normalize_tags_none():
    assert utils_module.normalize_tags(None) == []


def test_normalize_tags_csv():
    assert utils_module.normalize_tags("a, b, c") == ["a", "b", "c"]
    assert utils_module.normalize_tags("single") == ["single"]
    assert utils_module.normalize_tags("") == []


def test_normalize_tags_list():
    assert utils_module.normalize_tags(["x", " y ", ""]) == ["x", "y"]


def test_normalize_tags_non_string_items():
    assert utils_module.normalize_tags([1, None, "valid"]) == ["valid"]


def test_normalize_tags_unsupported_type():
    assert utils_module.normalize_tags(42) == []


# ---------------------------------------------------------------------------
# normalize_strings
# ---------------------------------------------------------------------------


def test_normalize_strings_none():
    assert utils_module.normalize_strings(None) == []


def test_normalize_strings_csv():
    assert utils_module.normalize_strings("a,b,c") == ["a", "b", "c"]


def test_normalize_strings_list():
    assert utils_module.normalize_strings(["x", " y ", ""]) == ["x", "y"]


def test_normalize_strings_unsupported():
    assert utils_module.normalize_strings(0) == []


# ---------------------------------------------------------------------------
# dedupe_keep_order
# ---------------------------------------------------------------------------


def test_dedupe_keep_order_basic():
    assert utils_module.dedupe_keep_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_keep_order_empty_strings():
    assert utils_module.dedupe_keep_order(["", "a", ""]) == ["a"]


def test_dedupe_keep_order_empty_list():
    assert utils_module.dedupe_keep_order([]) == []


def test_dedupe_keep_order_single():
    assert utils_module.dedupe_keep_order(["x"]) == ["x"]


# ---------------------------------------------------------------------------
# normalize_project_ids
# ---------------------------------------------------------------------------


def test_normalize_project_ids_none():
    assert utils_module.normalize_project_ids(None, max_projects=5) == []


def test_normalize_project_ids_csv():
    result = utils_module.normalize_project_ids("p1, p2, p1", max_projects=5)
    assert result == ["p1", "p2"]


def test_normalize_project_ids_list():
    result = utils_module.normalize_project_ids(["p1", "p2", "p3"], max_projects=2)
    assert result == ["p1", "p2"]


def test_normalize_project_ids_unsupported():
    assert utils_module.normalize_project_ids(42, max_projects=5) == []


# ---------------------------------------------------------------------------
# normalize_response_format
# ---------------------------------------------------------------------------


def test_normalize_response_format_valid():
    assert utils_module.normalize_response_format("json") == "json"
    assert utils_module.normalize_response_format("text") == "text"


def test_normalize_response_format_invalid():
    assert utils_module.normalize_response_format("xml") == "text"
    assert utils_module.normalize_response_format(None) == "text"
    assert utils_module.normalize_response_format("") == "text"
    assert utils_module.normalize_response_format(42) == "text"


# ---------------------------------------------------------------------------
# normalize_excerpt_chars
# ---------------------------------------------------------------------------


def test_normalize_excerpt_chars_within_bounds():
    result = utils_module.normalize_excerpt_chars(500)
    assert result == 500


def test_normalize_excerpt_chars_below_min():
    from constants import MIN_EXCERPT_CHARS
    result = utils_module.normalize_excerpt_chars(1)
    assert result == MIN_EXCERPT_CHARS


def test_normalize_excerpt_chars_above_max():
    from constants import MAX_EXCERPT_CHARS
    result = utils_module.normalize_excerpt_chars(999999)
    assert result == MAX_EXCERPT_CHARS


def test_normalize_excerpt_chars_non_int():
    from constants import DEFAULT_EXCERPT_CHARS
    result = utils_module.normalize_excerpt_chars("abc")
    assert isinstance(result, int)
