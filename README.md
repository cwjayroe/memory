# Project Memory (Cursor + MCP)

This folder provides a local, multi-project memory system for Cursor/Codex using MCP.

## What this supports
- many projects over time (`project_id` namespaces)
- many repos per project
- startup context preload using a reusable 3-layer pattern
- manual ingestion and policy-driven pruning

## Files
- `mcp_server.py`: MCP server (`search_context`, `store_memory`, `list_memories`, `get_memory`, `delete_memory`)
- `ingest.py`: ingestion and maintenance CLI
- `contracts.py`: typed request/argument models for MCP tools and ingest commands
- `shared.py`: shared helpers and mem0 config wiring
- `manifest.py`: manifest v2 model, migration, context-plan, and inference utilities
- `projects.yaml`: manifest v2 (projects, repos, defaults, context packs)
- `cursor-templates/`: reusable `.cursorrules` templates
- `skills/project-memory/SKILL.md`: Codex skill for active-project resolution and preload

## Prerequisites
- `ollama serve`
- Python env: `/Users/willjayroe/Desktop/repos/ai-tooling/.env`

## Tests and Coverage Gate
Run tests from the `memory/` directory:

```bash
pytest -q tests
```

Generate module coverage for the two confidence-critical files:

```bash
mkdir -p .artifacts/coverage
COVERAGE_FILE=.artifacts/coverage/.coverage \
pytest -q tests \
  --cov=. \
  --cov-report=term-missing \
  --cov-report=json:.artifacts/coverage/coverage.json \
  --cov-report=xml:.artifacts/coverage/coverage.xml \
  --cov-report=html:.artifacts/coverage/html
```

Enforce per-module minimums from `.artifacts/coverage/coverage.json`:

```bash
python - <<'PY'
import json
import pathlib
import sys

thresholds = {
    "mcp_server.py": 80.0,
    "ingest.py": 50.0,
}

report = json.loads(pathlib.Path(".artifacts/coverage/coverage.json").read_text())
files = report.get("files", {})
failures = []

for module_name, minimum in thresholds.items():
    entry = next((meta for path, meta in files.items() if path.endswith(module_name)), None)
    if entry is None:
        failures.append(f"{module_name}: missing from coverage report")
        continue
    actual = float(entry["summary"]["percent_covered"])
    print(f"{module_name}: {actual:.2f}% (required {minimum:.2f}%)")
    if actual < minimum:
        failures.append(f"{module_name}: {actual:.2f}% < {minimum:.2f}%")

if failures:
    print("\\nCoverage gate failed:")
    for failure in failures:
        print(f"- {failure}")
    sys.exit(1)

print("\\nCoverage gate passed.")
PY
```

## Manifest v2 model
`projects.yaml` is the source of truth.

Top-level sections:
- `defaults`: ranking and preload defaults
- `projects`: project metadata and associated repos
- `repos`: repo root + include/exclude + `default_active_project`
- `context_packs`: reusable startup preload definitions (default: `default_3_layer`)

## Active project resolution
1. explicit override (skill: `memory use <project_id>`)
2. repo `default_active_project` from manifest
3. `PROJECT_ID` env fallback

## `search_context` API notes
Required:
- `query`

Scope:
- `project_id` (explicit single-project)
- `project_ids` (explicit multi-project)
- if omitted, MCP infers project scope from query text + manifest metadata

Filters:
- `repo`, `path_prefix`, `tags`, `categories`

Ranking controls:
- `ranking_mode` (`hybrid_weighted_rerank` or `hybrid_weighted`)
- `token_budget` (`600`-`4000`, default `1800`)
- `candidate_pool`
- `rerank_top_n`
- `limit`
- `debug`

Response controls:
- `response_format` (`text` or `json`, default `text`)
- `include_full_text` (`false` by default; only selected results include full bodies)
- `excerpt_chars` (`120`-`4000`, default `420`)

`search_context` response header includes:
- `scope_source=explicit|inferred|fallback-default|fallback-retry`
- `resolved_projects=<csv>`

Default `text` mode is concise and excerpted. `search_context` excerpts are query-centered, so the returned body is anchored around the best local match instead of the start of the stored chunk. Use `response_format=json` when callers need stable fields such as `id`, `excerpt`, and `excerpt_info`.

## `list_memories` and `get_memory` notes
- `list_memories` now supports the same `response_format`, `include_full_text`, and `excerpt_chars` options.
- Default `list_memories` output is prefix-based and clearly marked as a snippet, not the whole memory.
- `get_memory` is the canonical exact-read endpoint for one memory by `memory_id`.
- `get_memory` returns the full untruncated memory body in both `text` and `json` modes.

If inferred scope returns no results, MCP retries once with:
- `PROJECT_ID + defaults.org_practice_projects`

## Runtime env vars (MCP)
- `PROJECT_ID`: fallback project when explicit/inferred scope is unavailable
- `PROJECT_MEMORY_MANIFEST_PATH`: optional path to manifest for inference (default `memory/projects.yaml`)
- `PROJECT_MEMORY_INFERENCE_MAX_PROJECTS`: inferred project cap (default `2`)
- `PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS`: per-project search timeout (default `8.0`)
- `PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS`: global search timeout (default `20.0`)

## New ingestion commands
```bash
# Create/update a project in manifest v2
python -m memory.ingest project-init \
  --project checkout-tax \
  --repos customcheckout,shopify-discount-import-dapr \
  --description "Checkout tax feature" \
  --tags tax,checkout \
  --set-repo-defaults

# Preview resolved startup payloads for a repo (3 layers)
python -m memory.ingest context-plan \
  --repo customcheckout

# Preview retention policy effects for a project
python -m memory.ingest policy-run \
  --project checkout-tax \
  --mode dry-run

# Apply retention policy
python -m memory.ingest policy-run \
  --project checkout-tax \
  --mode apply
```

## Existing ingestion commands (still supported)
```bash
python -m memory.ingest repo --project <project_id> --repo <repo_name> --mode mixed
python -m memory.ingest file --project <project_id> --repo <repo_name> --path /abs/path/file.py
python -m memory.ingest note --project <project_id> --repo <repo_name> --category decision --text "..."
python -m memory.ingest list --project <project_id> --repo <repo_name> --limit 20
python -m memory.ingest prune --project <project_id> --repo <repo_name>
python -m memory.ingest clear --project <project_id>
```

## PDF ingestion behavior
- PDFs are ingested page-by-page, but page text is now split on paragraph, bullet, and section-style boundaries before raw character chunking.
- Each stored PDF chunk keeps page provenance and a stable chunk label such as `page-7::chunk-2`.
- After shipping a chunking change, you must re-ingest affected PDFs for retrieval quality to improve. Existing stored page chunks are not rewritten automatically.

## PRD ingestion profile (PDF + docs)
`projects.yaml` includes a reusable `product-docs` repo profile rooted at `/Users/willjayroe/Downloads` with `pdf/md/rst/txt` globs and default tags (`product-docs`, `prd`).

Use it for feature PRDs:

```bash
python -m memory.ingest file \
  --project automatic-discounts \
  --repo product-docs \
  --path "/Users/willjayroe/Downloads/Discounts Product Doc.pdf" \
  --mode headings \
  --tags prd,requirements,discounts
```

For bulk PRD ingestion from the profile root:

```bash
python -m memory.ingest repo \
  --project automatic-discounts \
  --repo product-docs \
  --mode headings
```

## Retention policy (`policy-run`)
- Tier A: `decision`, `architecture` never auto-pruned
- Tier B: `summary` capped per `(repo, topic_key)` with keep limit (default `5`)
- Tier C: `code`, `documentation` prune duplicate fingerprints and stale entries (default `45` days)

## Cursor templates
Use `memory/cursor-templates/*.cursorrules` as placeholders for any project/repo.

## Codex integration
Codex does not read `.cursorrules`; use the skill in:
- `memory/skills/project-memory/SKILL.md`

The skill is MCP-only and intentionally does not call local scripts.
Use `ingest.py` as an external/manual workflow for bulk and file ingestion.

Add a short line in repo `AGENTS.md` to invoke the skill at conversation start.

## External CLI Debug Harness
Use one-off CLI harnesses to debug `mcp_server.py` under `debugpy` without changing MCP runtime config.

1) Initialize + list tools:
```bash
/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python - <<'PY'
import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m", "debugpy",
            "--listen", "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/ai-tooling/.worktrees/cursor-memories/memory/mcp_server.py",
        ],
        env={**os.environ, "PROJECT_ID": "customcheckout-practices"},
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print([t.name for t in tools.tools])

asyncio.run(main())
PY
```

2) Search flow:
```bash
/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python - <<'PY'
import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m", "debugpy",
            "--listen", "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/ai-tooling/.worktrees/cursor-memories/memory/mcp_server.py",
        ],
        env={**os.environ, "PROJECT_ID": "customcheckout-practices"},
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool("search_context", {
                "query": "automatic discounts constraints in customcheckout",
                "repo": "customcheckout",
                "limit": 4,
            })
            print(result.content[0].text if result.content else "no content")

asyncio.run(main())
PY
```

Attach your IDE debugger to `127.0.0.1:5678` after starting either command.

3) Store/list/delete roundtrip:
```bash
/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python - <<'PY'
import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m", "debugpy",
            "--listen", "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/ai-tooling/.worktrees/cursor-memories/memory/mcp_server.py",
        ],
        env={**os.environ, "PROJECT_ID": "customcheckout-practices"},
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            store = await s.call_tool("store_memory", {
                "project_id": "customcheckout-practices",
                "content": "debug roundtrip memory",
                "repo": "customcheckout",
                "category": "summary",
                "source_kind": "summary",
                "upsert_key": "debug-roundtrip",
            })
            print("STORE:", store.content[0].text)
            listed = await s.call_tool("list_memories", {
                "project_id": "customcheckout-practices",
                "repo": "customcheckout",
                "limit": 5,
            })
            print("LIST:", listed.content[0].text.splitlines()[0])
            deleted = await s.call_tool("delete_memory", {
                "project_id": "customcheckout-practices",
                "upsert_key": "debug-roundtrip",
            })
            print("DELETE:", deleted.content[0].text)

asyncio.run(main())
PY
```

4) Exact body fetch after search:
```bash
/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python - <<'PY'
import asyncio, json, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/python",
        args=["/Users/willjayroe/Desktop/repos/ai-tooling/.worktrees/cursor-memories/memory/mcp_server.py"],
        env={**os.environ, "PROJECT_ID": "customcheckout-practices"},
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            search = await s.call_tool("search_context", {
                "query": "charge date updates cadence",
                "project_id": "multiple-queued-charges",
                "response_format": "json",
                "limit": 3,
            })
            payload = json.loads(search.content[0].text)
            first_id = payload["items"][0]["id"]
            exact = await s.call_tool("get_memory", {
                "project_id": "multiple-queued-charges",
                "memory_id": first_id,
                "response_format": "json",
            })
            print(exact.content[0].text)

asyncio.run(main())
PY
```

## Troubleshooting
- If a relevant rule exists in a stored memory but the old system only showed unrelated prefix text, the likely cause was coarse PDF page chunks combined with prefix truncation.
- The current flow fixes that by returning query-centered excerpts from selected search results and exposing `get_memory` for exact full-body retrieval.
- If the search result still looks too broad, re-ingest the source PDF so the newer boundary-aware chunker can replace the old page-sized chunks.

## Entrypoints
Both modes are supported:
- package-style: `python -m memory.ingest`, `python -m memory.mcp_server`
- direct scripts: `python memory/ingest.py`, `python memory/mcp_server.py`

## Dependencies
```bash
/Users/willjayroe/Desktop/repos/ai-tooling/.env/bin/pip install -r \
  /Users/willjayroe/Desktop/repos/ai-tooling/.worktrees/cursor-memories/memory/requirements.txt
```
