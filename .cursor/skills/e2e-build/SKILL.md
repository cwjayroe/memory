---
name: e2e-build
description: End-to-end project build from a single document. Accepts a prompt containing project details (spec, design doc, feature brief), plans the implementation, builds it via delegated agents, and QAs the result — all in one invocation. Use when the user provides a project spec and wants the full lifecycle handled, says "build this", "e2e build", "implement this doc", or wants to avoid the two-step plan-then-orchestrate workflow.
---

# E2E Build

Accept a single document describing a project. Plan it, build it, QA it. The coordinator stays lean — memory MCP is the shared state bus; agents fetch what they need via memory keys.

## Agents

This skill bundles four purpose-built, memory-native agents:

- **Planner** (`agents/planner.md`): Analyzes input document and codebase → structured phased plan stored in memory.
- **Builder** (`agents/builder.md`): Creates new files or modifies existing ones. Unified agent — no Creator/Integrator split.
- **Reviewer** (`agents/reviewer.md`): Per-batch correctness review including spec compliance and cross-file consistency.
- **QA** (`agents/qa.md`): End-to-end quality assurance — tests, coverage, lint, imports, completeness audit.

## Memory Key Schema

All inter-phase communication flows through memory MCP using deterministic upsert keys. The `{build_id}` is derived from the input document (slugified title + 6-char timestamp hash, e.g., `add-webhook-support-a3f2c1`).

| Phase | Upsert Key | Category | Source Kind | Priority |
|-------|-----------|----------|-------------|----------|
| Input | `{repo}::e2e-build::{build_id}::input-doc` | documentation | reference | high |
| Plan | `{repo}::e2e-build::{build_id}::architecture-snapshot` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::plan` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::plan-phase-{N}` | architecture | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::batch-{B}-result` | code | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::progress` | architecture | summary | high |
| Review | `{repo}::e2e-build::{build_id}::review-batch-{B}` | code | summary | normal |
| QA | `{repo}::e2e-build::{build_id}::qa-report` | decision | summary | high |
| Done | `{repo}::e2e-build::{build_id}::completion` | decision | summary | high |

All writes use `upsert_key` for idempotency. All writes include `tags=["e2e-build", build_id]` and `repo="{repo}"`.

## Execution Protocol

### Phase 0: Accept & Store Input

1. Receive the user's prompt containing the project document.
2. Derive `build_id`: slugify the document title (or first 40 chars) + 6-char hash of current timestamp.
3. Store the input document in memory:
   ```
   store_memory(
     content=<full document>,
     category="documentation",
     source_kind="reference",
     priority="high",
     upsert_key="{repo}::e2e-build::{build_id}::input-doc",
     repo="{repo}",
     tags=["e2e-build", build_id]
   )
   ```
4. Drop the document from coordinator context. Retain only `build_id` and `repo`.

### Phase 1: Plan (Planner Agent)

1. Read `agents/planner.md` from this skill folder.
2. Launch a single `Task` with `subagent_type="generalPurpose"`:
   - Prompt includes: planner protocol + memory keys (input-doc, architecture-snapshot, plan, plan-phase template) + repo name.
   - The planner agent will:
     a. Retrieve the input doc from memory via `get_memory`.
     b. Explore the codebase to understand current architecture.
     c. Store an architecture snapshot in memory.
     d. Produce a structured plan and store it in memory.
     e. Store per-phase specs and link them to the plan.
     f. Return: build_id, total phases, total tasks, one-line phase summaries.
3. Initialize todos from the phase summaries.
4. **Approval gate** (configurable, default: autonomous):
   - If the user's prompt contains keywords like "pause for approval", "review first", or "wait before building": present the plan summary and wait for user confirmation.
   - Otherwise: proceed directly to Phase 2.

### Phase 2: Build (Batched Execution)

For each phase N (sequential phases, parallel tasks within):

**2a. Retrieve phase spec**
- Use `get_memory` with upsert key `{repo}::e2e-build::{build_id}::plan-phase-{N}`.
- Read ONLY the task list and file paths. Do NOT read source files.

**2b. Decompose into parallel batches**
- Group tasks that can execute concurrently (independent files, no import dependencies between them).
- Max 3 Builder agents per batch.
- Dependency rules:
  - A file must exist before another file can import from it.
  - Tasks on the same file must be sequential.
  - Cross-phase tasks are always sequential.

**2c. Delegate each batch**
For each task in the batch:
1. Read `agents/builder.md` from this skill folder.
2. Build prompt: builder protocol + task spec from the phase memory + memory keys for architecture snapshot and phase spec.
3. Instruct the builder to store its result at `{repo}::e2e-build::{build_id}::batch-{B}-task-{T}-result`.
4. Use `model="fast"` for tasks with `model_hint="fast"` in the spec.

**2d. Review each batch**
After all builders in a batch complete:
1. Read `agents/reviewer.md` from this skill folder.
2. Launch a Reviewer task with: reviewer protocol + list of touched files + memory key for the phase spec.
3. Reviewer stores report at `{repo}::e2e-build::{build_id}::review-batch-{B}`.
4. If FAIL: re-launch failing builder task with error context from the review report (max 3 retries per task).
5. If PASS: mark todos `completed`, advance to next batch.

**2e. Update progress**
After each phase completes, upsert progress:
```
store_memory(
  content="Completed phases: [1..N]. Remaining: [N+1..total]. Files created: [...]. Files modified: [...].",
  category="architecture",
  source_kind="summary",
  priority="high",
  upsert_key="{repo}::e2e-build::{build_id}::progress",
  repo="{repo}",
  tags=["e2e-build", build_id]
)
```

### Phase 3: QA (QA Agent)

After all build phases complete:

1. Read `agents/qa.md` from this skill folder.
2. Launch a single `Task` with:
   - QA protocol + memory keys for plan, progress, and all review reports.
3. QA agent will:
   a. Retrieve plan and progress from memory.
   b. Run the test suite and coverage checks.
   c. Lint all created/modified files.
   d. Verify imports and module wiring.
   e. Audit completeness against the plan.
   f. Store the QA report in memory.
   g. Return: PASS/FAIL + summary.
4. If FAIL:
   - Parse blocker list from the QA return.
   - Launch targeted Builder agents to fix each blocker (with QA report memory key for context).
   - Re-run QA (max 2 total QA cycles to prevent infinite loops).
5. If PASS (or max cycles exhausted): proceed to Phase 4.

### Phase 4: Completion

1. Store completion summary in memory:
   ```
   store_memory(
     content="Build {build_id} complete. Files created: [...]. Files modified: [...]. Test status: PASS/FAIL. Coverage: X%. Known issues: [...].",
     category="decision",
     source_kind="summary",
     priority="high",
     upsert_key="{repo}::e2e-build::{build_id}::completion",
     repo="{repo}",
     tags=["e2e-build", build_id, "completion"]
   )
   ```
2. Link QA report to completion: `link_memories(source=qa_report_id, target=completion_id, relation="implements")`.
3. Present the user with a concise summary: what was built, test status, coverage, remaining issues.

## Context Window Discipline

- The coordinator NEVER reads source files. Agents read them directly.
- The input document is stored in memory immediately and dropped from context.
- Phase specs are stored in memory by the planner. The coordinator retrieves only task lists (file paths + one-line descriptions).
- All detailed context is accessed only by agents via memory keys.
- Agent return values must be ≤20 lines. Detailed results go into memory.
- The coordinator holds at most: `build_id`, `repo`, current phase number, todo list, and the latest batch file list.

## Model Selection

- `model="fast"` for: tasks with `model_hint="fast"`, progress memory updates, simple config edits.
- Default model for: planner agent, QA agent, complex builder tasks, reviewer agent.

## Error Handling

- **Planner failure**: Surface error to user. Do not proceed to build.
- **Builder failure after 3 review retries**: Store failure in memory, skip task, flag it in QA phase.
- **QA failure after 2 cycles**: Complete with "partial success" status. Include all known issues in the completion summary.
- **All errors** are stored in memory so they survive context window eviction.
