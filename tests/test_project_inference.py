from __future__ import annotations


def _resolve_scope(
    helpers_module,
    contracts_module,
    server_config_module,
    *,
    query: str,
    repo: str | None = None,
):
    request = contracts_module.SearchContextRequest.from_arguments(
        {"query": query, "repo": repo, "limit": 8},
        policy=contracts_module.SearchContextParsePolicy(max_projects_per_query=10),
    )
    config = server_config_module.ServerConfig(
        max_projects_per_query=10,
        manifest_path="/tmp/projects.yaml",
        inference_max_projects=2,
    )
    return helpers_module._resolve_search_scope(request, config)


def test_infer_from_project_id_tokens(
    helpers_module, contracts_module, server_config_module, manifest_module, monkeypatch
):
    monkeypatch.setattr(
        manifest_module,
        "load_project_index_with_cache",
        lambda **_kwargs: {
            "projects": {
                "automatic-discounts": {"tags": ["discounts", "checkout"], "repos": ["customcheckout"]},
                "customcheckout-practices": {"tags": ["standards"], "repos": ["customcheckout"]},
            },
            "org_practice_projects": ["customcheckout-practices"],
        },
    )

    _, scope_source, inferred = _resolve_scope(
        helpers_module,
        contracts_module,
        server_config_module,
        query="show me the automatic discounts product doc",
    )
    assert scope_source == "inferred"
    assert inferred
    assert inferred[0][0] == "automatic-discounts"


def test_infer_from_tags(
    helpers_module, contracts_module, server_config_module, manifest_module, monkeypatch
):
    monkeypatch.setattr(
        manifest_module,
        "load_project_index_with_cache",
        lambda **_kwargs: {
            "projects": {
                "automatic-discounts": {"tags": ["discounts"], "repos": ["customcheckout"]},
                "customcheckout-practices": {"tags": ["coding", "standards", "architecture"], "repos": ["customcheckout"]},
            },
            "org_practice_projects": ["customcheckout-practices"],
        },
    )

    _, scope_source, inferred = _resolve_scope(
        helpers_module,
        contracts_module,
        server_config_module,
        query="need coding standards and architecture constraints",
    )
    assert scope_source == "inferred"
    assert inferred
    assert inferred[0][0] == "customcheckout-practices"


def test_infer_uses_repo_hint(
    helpers_module, contracts_module, server_config_module, manifest_module, monkeypatch
):
    monkeypatch.setattr(
        manifest_module,
        "load_project_index_with_cache",
        lambda **_kwargs: {
            "projects": {
                "automatic-discounts": {
                    "tags": ["discounts"],
                    "repos": ["customcheckout", "shopify-discount-import-dapr"],
                },
                "checkout-tax": {"tags": ["tax"], "repos": ["customcheckout"]},
            },
            "org_practice_projects": [],
        },
    )

    _, scope_source, inferred = _resolve_scope(
        helpers_module,
        contracts_module,
        server_config_module,
        query="discount sync service behavior",
        repo="shopify-discount-import-dapr",
    )
    assert scope_source == "inferred"
    assert inferred
    assert inferred[0][0] == "automatic-discounts"


def test_infer_top_two_deterministic_tie_break(
    helpers_module, contracts_module, server_config_module, manifest_module, monkeypatch
):
    monkeypatch.setattr(
        manifest_module,
        "load_project_index_with_cache",
        lambda **_kwargs: {
            "projects": {
                "alpha-checkout": {"tags": ["checkout"], "repos": []},
                "beta-checkout": {"tags": ["checkout"], "repos": []},
                "gamma-checkout": {"tags": ["checkout"], "repos": []},
            },
            "org_practice_projects": [],
        },
    )

    _, scope_source, inferred = _resolve_scope(
        helpers_module,
        contracts_module,
        server_config_module,
        query="checkout",
    )
    assert scope_source == "inferred"
    assert [project_id for project_id, _ in inferred] == ["alpha-checkout", "beta-checkout"]
