---
name: project-memory
description: Retrieve and persist multi-project engineering context using the local project-memory MCP. Use when starting a conversation, switching project focus, capturing decisions, or loading prior context across repos without manual recap.
---

# Project Memory Skill

Use MCP tools only. Do not assume local script paths are available in the skill runtime.

## Required MCP Tools
- `search_context`
- `store_memory`
- `list_memories`
- `get_memory`
- `delete_memory`

## Interface Commands
- `memory use <project_id>`
  - Set conversation-scoped active project override.
- `memory practices <project_ids_csv>`
  - Set org/team best-practice project IDs for this conversation.
- `memory status`
  - Show current repo, active project override, practice projects, and MCP fallback behavior.
- `memory preload [topic]`
  - Load startup context using layered MCP retrieval.
- `memory capture decision: <text>`
  - Persist a decision with structured metadata.
- `memory capture summary: <text>`
  - Persist an implementation summary with structured metadata.

## Session State
- `active_project`: optional override from `memory use`.
- `practice_projects`: optional list from `memory practices`.
- `repo`: infer from current working repo when available.
- `default_project`: MCP `PROJECT_ID` fallback when no explicit project scope is provided.

## Workflow (MCP-Only)
1. Resolve scope
- Build `project_ids` in this order:
  - if `active_project` exists: `[active_project] + practice_projects`
  - else if `practice_projects` exists: `practice_projects`
  - else: omit `project_id` and `project_ids` so MCP infers project scope from the prompt.
- Dedupe while preserving order.
- MCP fallback behavior when scope is omitted:
  - infer from query + manifest metadata
  - if no inferred hit, retry with `PROJECT_ID + org_practice_projects`

2. Preload context
- Layer 1 (practices/constraints):
  - `search_context` with query:
    - `engineering best practices, architecture constraints, coding standards`
  - Include `project_ids` when available.
  - Use `categories=["decision","architecture","summary"]`, `limit=4`.
- Layer 2 (active project global), only when `active_project` is set:
  - Query:
    - `{active_project} architecture, recent decisions, constraints`
  - Include `project_ids`.
  - Use `categories=["decision","architecture","summary","documentation"]`, `limit=4`.
- Layer 3 (repo focus), when repo is known:
  - Query:
    - `{active_project or "current project"} in repo {repo}, critical files and flow constraints`
  - Include `project_ids` when available and `repo=<repo>`.
  - Use `categories=["code","summary","decision","architecture","documentation"]`, `limit=4`.

3. Capture durable context
- For decisions:
  - Call `store_memory` with:
    - `project_id`: `active_project` when set (otherwise omit for fallback)
    - `repo`: current repo if known
    - `category="decision"`
    - `source_kind="summary"`
    - `tags`: include stable tags (for example `decision,architecture`)
- For implementation recaps:
  - Call `store_memory` with `category="summary"` and project/repo metadata.

4. Refresh strategy
- For quick updates in conversation, use `store_memory`.
- For bulk or file-level ingestion, use external ingestion workflows outside this skill runtime.

## Guardrails
- Do not hardcode feature names, absolute paths, or repo-specific assumptions.
- Prefer explicit `project_ids` for blended retrieval and `project_id` for single-project operations.
- Omit project scope only when you want inference based on prompt intent.
- Keep startup retrieval tight (typically 6-10 total memories).
- Always include project/repo metadata when storing memory if known.
- Use `response_format="json"` when you need exact `id`, `excerpt`, or metadata fields.
- Use `get_memory` after `search_context` or `list_memories` when you need the full untruncated body of a specific memory.

## Reference
- AGENTS snippet: `references/agents-snippet.md`
