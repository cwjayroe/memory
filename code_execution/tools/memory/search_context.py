"""search_context — Search scoped memory for architectural context, decisions, and code-aware summaries. Supports one or many scopes via project_id/project_ids plus repo/path/category/tag filtering."""

from __future__ import annotations

from code_execution.bridge import call_tool


def search_context(
    query: str,
    *,
    after_date: str | None = None,
    before_date: str | None = None,
    candidate_pool: int | None = None,
    categories: list | str | None = None,
    debug: bool = False,
    excerpt_chars: int = 420,
    highlight: bool = False,
    include_full_text: bool = False,
    limit: int = 8,
    path_prefix: str | None = None,
    project_id: str | None = None,
    project_ids: list | str | None = None,
    ranking_mode: str = 'hybrid_weighted_rerank',
    repo: str | None = None,
    rerank_top_n: int = 40,
    response_format: str = 'text',
    search_all_scopes: bool = False,
    tags: list | str | None = None,
    token_budget: int = 1800,
) -> str:
    """Search scoped memory for architectural context, decisions, and code-aware summaries. Supports one or many scopes via project_id/project_ids plus repo/path/category/tag filtering.

    Args:
        query: 
        after_date: ISO 8601 datetime — only return memories updated after this date (optional)
        before_date: ISO 8601 datetime — only return memories updated before this date (optional)
        candidate_pool:  (optional)
        categories:  (optional)
        debug:  (optional)
        excerpt_chars:  (optional)
        highlight: Wrap matching query tokens in **bold** in excerpt text (optional)
        include_full_text:  (optional)
        limit:  (optional)
        path_prefix:  (optional)
        project_id:  (optional)
        project_ids:  (optional)
        ranking_mode:  (optional)
        repo:  (optional)
        rerank_top_n:  (optional)
        response_format:  (one of: 'text', 'json') (optional)
        search_all_scopes: Search across all manifest scopes (ignores project_id/project_ids) (optional)
        tags:  (optional)
        token_budget:  (optional)"""
    kwargs: dict = {}
    kwargs["query"] = query
    if after_date is not None:
        kwargs["after_date"] = after_date
    if before_date is not None:
        kwargs["before_date"] = before_date
    if candidate_pool is not None:
        kwargs["candidate_pool"] = candidate_pool
    if categories is not None:
        kwargs["categories"] = categories
    if debug is not None:
        kwargs["debug"] = debug
    if excerpt_chars is not None:
        kwargs["excerpt_chars"] = excerpt_chars
    if highlight is not None:
        kwargs["highlight"] = highlight
    if include_full_text is not None:
        kwargs["include_full_text"] = include_full_text
    if limit is not None:
        kwargs["limit"] = limit
    if path_prefix is not None:
        kwargs["path_prefix"] = path_prefix
    if project_id is not None:
        kwargs["project_id"] = project_id
    if project_ids is not None:
        kwargs["project_ids"] = project_ids
    if ranking_mode is not None:
        kwargs["ranking_mode"] = ranking_mode
    if repo is not None:
        kwargs["repo"] = repo
    if rerank_top_n is not None:
        kwargs["rerank_top_n"] = rerank_top_n
    if response_format is not None:
        kwargs["response_format"] = response_format
    if search_all_scopes is not None:
        kwargs["search_all_scopes"] = search_all_scopes
    if tags is not None:
        kwargs["tags"] = tags
    if token_budget is not None:
        kwargs["token_budget"] = token_budget
    return call_tool("search_context", **kwargs)
