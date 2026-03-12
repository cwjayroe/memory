---
name: memory
description: Resolve active scope, preload multi-scope engineering context, and persist durable implementation notes using the local memory MCP. Use when starting a conversation, switching scope, capturing decisions, or retrieving prior context across repos without a manual recap.
---

# Memory Skill

Use MCP tools only. Do not assume local script paths or package-style entrypoints are available in the skill runtime.

The implementation currently uses `project_id` as the storage and retrieval namespace key. In practice, that key can represent a project, domain, workstream, standards pack, migration, incident, or customer issue.

## Required MCP Tools
- `search_context`
- `store_memory`
- `list_memories`
- `get_memory`
- `delete_memory`

## Interface Commands
- `memory use <project_id>`
  - Set the conversation-scoped active scope override. The command keeps the current `project_id` interface name.
- `memory practices <project_ids_csv>`
  - Set practice scope IDs for this conversation. The command keeps the current `project_ids` interface name.
- `memory status`
  - Show current repo, active scope override, practice scopes, and fallback behavior.
- `memory preload [topic]`
  - Load startup context with layered MCP retrieval.
- `memory capture decision: <text>`
  - Persist a decision with structured metadata.
- `memory capture summary: <text>`
  - Persist an implementation summary with structured metadata.

## Session State
- `active_scope`: optional override from `memory use`.
- `practice_scopes`: optional list from `memory practices`.
- `repo`: infer from current working repo when available.
- `default_scope`: MCP `PROJECT_ID` fallback when no explicit scope is provided.

## Default Workflow
1. Resolve scope
- Build `project_ids` in this order:
  - if `active_scope` exists: `[active_scope] + practice_scopes`
  - else if `practice_scopes` exists: `practice_scopes`
  - else: omit `project_id` and `project_ids` so MCP infers scope from the prompt.
- Dedupe while preserving order.
- If scope is omitted, rely on MCP inference from query + manifest metadata.
- If inference returns no hit, MCP retries with `PROJECT_ID + org_practice_projects`.

2. Preload context
- Layer 1: practices and constraints
  - `search_context(query="engineering best practices, architecture constraints, coding standards", categories=["decision","architecture","summary"], limit=4)`
  - Include `project_ids` when available.
- Layer 2: active-scope context, only when `active_scope` is set
  - `search_context(query="{active_scope} architecture, recent decisions, constraints", categories=["decision","architecture","summary","documentation"], limit=4)`
  - Include `project_ids`.
- Layer 3: repo-focused context, when `repo` is known
  - `search_context(query="{active_scope or 'current scope'} in repo {repo}, critical files and flow constraints", categories=["code","summary","decision","architecture","documentation"], limit=4, repo=repo)`
  - Include `project_ids` when available.

3. Follow up precisely when needed
- Use `response_format="json"` when you need exact `id`, `excerpt`, or metadata fields from `search_context` or `list_memories`.
- Use `get_memory` after `search_context` or `list_memories` when you need the full untruncated body of a specific memory.
- Use `list_memories` for targeted audits or exact selectors; do not default to it for startup preload.

4. Capture durable context
- For quick updates in conversation, use `store_memory`.
- For decisions, call `store_memory` with:
  - `project_id`: `active_scope` when set, otherwise omit for fallback; `project_id` remains the current interface name
  - `repo`: current repo if known
  - `category="decision"`
  - `source_kind="summary"`
  - `tags`: stable tags such as `decision,architecture`
- For implementation recaps, call `store_memory` with `category="summary"` and scope/repo metadata.

## Guardrails
- Do not hardcode feature names, absolute paths, or repo-specific assumptions.
- Prefer explicit `project_ids` for blended retrieval and `project_id` for single-scope operations.
- Omit project scope only when you want inference based on prompt intent.
- Keep startup retrieval tight (typically 6-10 total memories).
- Always include scope/repo metadata when storing memory if known.
- Treat the local memory MCP as the default interaction surface for preload and capture.
- Do not use maintenance/admin MCP tools (`ingest_repo`, `ingest_file`, `prune_memories`, `init_project`, `clear_memories`) unless the user explicitly asks for repo maintenance or memory administration.
- Use external ingestion workflows outside this skill runtime for bulk or file-level maintenance.

## Reference
- `references/agents-snippet.md`: short AGENTS.md startup wording for invoking this skill.
