# Scoring and Ranking

## Hybrid Scoring Formula

Search results are ranked using a weighted combination of seven scoring components. The weights are defined in `scoring.py:ScoringWeights`:

| Component | Weight | Source | What It Measures |
|-----------|--------|--------|-----------------|
| Vector similarity | 0.25 | ChromaDB/mem0 | Semantic closeness of memory body to query (cosine distance of embeddings) |
| BM25 lexical | 0.18 | rank-bm25 | Term frequency / inverse document frequency match between query tokens and memory text + metadata |
| Repo metadata | 0.12 | SQLite | Boost for memories from the queried repo (exact repo match scores higher) |
| Recency | 0.08 | SQLite `updated_at` | More recently updated memories score higher (exponential decay over ~45 days) |
| Reranker | 0.22 | `bge-reranker-v2-m3` | Cross-encoder relevance score (direct query-document pair scoring) |
| Entity/graph | 0.10 | SQLite entities | Boost for memories sharing entities with the query or other high-ranking results |
| Access history | 0.05 | SQLite `access_log` | Boost for memories that have been retrieved frequently and ranked highly in past queries |

The weights sum to 1.0. They are applied after individual score normalization (min-max scaling per component).

**Priority modifier**: Memories stored with `priority=high` receive a +20% score boost; `priority=low` receive a -10% penalty.

---

## Ranking Modes

### `hybrid_weighted_rerank` (default)

1. Vector search retrieves up to `candidate_pool` candidates (default 200)
2. Pre-rerank hybrid scoring (vector + BM25 + metadata + recency + graph + access) selects top `rerank_top_n` (default 40)
3. Cross-encoder reranker re-scores the top-N candidates using direct query-document pair inference
4. Final hybrid score combines pre-rerank components with the reranker component
5. Results packed within token budget

**When to use**: Default choice. Higher precision, especially for technical queries where terminology matters. Cost: ~1-3s for reranker inference.

### `hybrid_weighted`

Same as above but skips step 3 (no reranker). Uses only vector + BM25 + metadata + recency + graph + access.

**When to use**: When latency matters more than precision, when the reranker model is unavailable, or for bulk ingestion-time queries where reranking overhead is unacceptable.

---

## Candidate Packing

After scoring, candidates are packed into the result set subject to diversity and budget constraints, defined in `scoring.py:PackingConfig`:

| Constraint | Default | Effect |
|-----------|---------|--------|
| `max_repo_results` | 3 | At most 3 results from any single repo |
| `max_category_results` | 3 | At most 3 results from any single category |
| `decision_categories` | `{decision, architecture}` | These categories are prioritized — their results are added to the pack first |
| `token_budget` | 1800 | Total token count of result bodies (estimated at ~4 chars/token) is capped at this value |

**Decision pinning**: Results with `category=decision` or `category=architecture` bypass normal diversity ordering and are included first. This ensures high-value architectural decisions always appear in context even when outnumbered by code summaries.

**Token budget enforcement**: Candidates are added to the pack in score order until the token budget is exceeded. The result set may contain fewer results than `limit` if earlier results are long.

---

## Reranker Setup

### Model

Default model: `BAAI/bge-reranker-v2-m3` (configurable via `PROJECT_MEMORY_RERANKER_MODEL`)

This is a cross-encoder model that takes `(query, document)` pairs and returns a direct relevance score. Unlike bi-encoders (which encode query and document independently), cross-encoders are more accurate but cannot be precomputed.

### Download

The model is downloaded from HuggingFace on first use. This can take a few minutes. Subsequent starts load from cache (`~/.cache/huggingface/`).

### Checking Reranker Status

```json
{"tool": "health_check", "arguments": {"skip_slow": false}}
```

`skip_slow=false` forces the model-load check. Response includes `reranker_ok` and `reranker_latency_ms`.

### Fallback Behavior

If the reranker model fails to load (missing dependencies, OOM, etc.), the server falls back to `hybrid_weighted` mode automatically for the affected query. The response `debug` output notes this fallback. No error is surfaced to the caller.

---

## Tuning Guide

### Token Budget

`token_budget` controls how much content is packed into the result. Larger budgets return more context but consume more of the agent's context window.

| Use Case | Recommended Budget |
|----------|-------------------|
| Quick fact lookup | 600–800 |
| Standard conversation preload | 1800 (default) |
| Deep codebase analysis | 3000–4000 |

Set per-request: `{"token_budget": 2400}` in `search_context`.

### Candidate Pool

`candidate_pool` controls how many vector search results are fetched before scoring. Larger pools improve recall (more chances to find the right result) at the cost of scoring overhead.

| Use Case | Recommended Pool |
|----------|-----------------|
| Small scope (<500 memories) | 50–100 |
| Medium scope (500–2000) | 100–200 (default) |
| Large scope (2000+) | 200–300 |

### Rerank Top-N

`rerank_top_n` controls how many pre-ranked candidates are passed to the cross-encoder. The cross-encoder is the most expensive step; reducing this improves latency.

| Priority | Recommended Top-N |
|----------|------------------|
| Low latency | 15–25 |
| Balanced | 40 (default) |
| High precision | 60–80 |

### Result Limit

`limit` sets the maximum number of results to return (after packing). Note that token budget may reduce results below this limit.

### Debug Mode

Pass `debug=true` to `search_context` to get scoring metadata in the response:

```json
{
  "query": "payment retry logic",
  "debug": true
}
```

Response includes per-result score breakdown: `vector_score`, `bm25_score`, `metadata_score`, `reranker_score`, `final_score`.

---

## Lexical Document Construction

For BM25 scoring, each memory is represented as a concatenation of:
- Memory body text
- Tags (normalized)
- Category and repo name
- Source path

This means BM25 matches on exact terms in any of these fields, giving keyword-dense searches an edge even when semantic similarity is moderate.

---

## Access History Scoring

The `access_log` SQLite table records every search result returned, including the query and the rank position. Memories that have been retrieved and ranked in the top-3 positions frequently score higher in future searches. This creates a self-reinforcing signal: useful memories become easier to find over time.

This is a small component (0.05 weight) and primarily helps disambiguate ties between similar candidates.
