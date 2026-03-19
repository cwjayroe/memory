---
name: e2e-build
description: "Execute a pre-planned implementation. Retrieves the plan from memory (produced by e2e-plan), builds it via sequential delegated agents, reviews each phase, and QAs the result. Invoke with: /e2e-build {build_id}"
---

# E2E Build

Execute a plan that was produced by the `e2e-plan` skill. Retrieve it from memory, build it phase by phase, review each phase, and QA the result. The coordinator handles all memory persistence — subagents are pure computation.

**Prerequisites**: Run `/e2e-plan` first to produce and store the plan. This skill expects the plan to already exist in memory.

## Agents

This skill uses three purpose-built agents. None call MCP tools — they receive all context in the task description and return structured output.

- **Builder** (`agents/builder.md`): Creates new files or modifies existing ones. Consumes enriched task specs (interface contracts, pattern references, test strategies) → returns result summary.
- **Reviewer** (`agents/reviewer.md`): Per-phase correctness review including spec compliance, interface contract validation, preserve-list validation, and cross-file consistency → returns review report.
- **QA** (`agents/qa.md`): End-to-end quality assurance — tests, coverage, lint, imports, completeness audit → returns QA report.

## Memory Key Schema

The plan artifacts are already stored by `e2e-plan`. This skill reads them and adds build/review/QA artifacts.

| Phase | Upsert Key | Category | Source Kind | Priority |
|-------|-----------|----------|-------------|----------|
| *Read* | `{repo}::e2e-build::{build_id}::input-doc` | documentation | reference | high |
| *Read* | `{repo}::e2e-build::{build_id}::architecture-snapshot` | architecture | summary | high |
| *Read* | `{repo}::e2e-build::{build_id}::plan` | architecture | summary | high |
| *Read* | `{repo}::e2e-build::{build_id}::plan-phase-{N}` | architecture | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::phase-{N}-task-{T}-result` | code | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::progress` | architecture | summary | high |
| Review | `{repo}::e2e-build::{build_id}::review-phase-{N}` | code | summary | normal |
| QA | `{repo}::e2e-build::{build_id}::qa-report` | decision | summary | high |
| Baseline | `{repo}::e2e-build::{build_id}::test-baseline` | code | summary | high |
| Done | `{repo}::e2e-build::{build_id}::completion` | decision | summary | high |

All writes use `upsert_key` for idempotency. All writes include `tags=["e2e-build", build_id]` and `repo="{repo}"`.

## Execution Protocol

### Phase 0: Retrieve Plan

1. Parse the `build_id` from the user's invocation (e.g., `/e2e-build add-webhook-support-a3f2c1`).
2. Retrieve the plan from memory:
   ```
   get_memory(upsert_key="{repo}::e2e-build::{build_id}::plan")
   ```
   If not found: tell the user to run `/e2e-plan` first. Halt.
3. Retrieve the architecture snapshot:
   ```
   get_memory(upsert_key="{repo}::e2e-build::{build_id}::architecture-snapshot")
   ```
4. Parse the plan: extract phase count, task counts, file lists. Initialize todos.
5. **Capture pre-build test baseline** (for existing systems):
   - Run the project's test suite: `python -m pytest -q` and capture the output.
   - Store the baseline in memory:
     ```
     store_memory(
       content="Pre-build test baseline:\nTotal: X, Passed: Y, Failed: Z, Errors: W\nFailing tests: [list of test_file::test_name]\nCoverage: X%",
       category="code",
       source_kind="summary",
       priority="high",
       upsert_key="{repo}::e2e-build::{build_id}::test-baseline",
       repo="{repo}",
       tags=["e2e-build", build_id]
     )
     ```
   - If no test suite exists (brand new project), store: "No pre-existing test suite."

### Phase 1: Build (Builder Agent — Sequential Execution)

For each phase N (sequential phases, sequential tasks within):

**1a. Retrieve phase spec**
```
get_memory(upsert_key="{repo}::e2e-build::{build_id}::plan-phase-{N}")
```

**1b. Execute tasks sequentially**
For each task T in the phase (**one at a time**):
1. Read `agents/builder.md` from this skill folder.
2. Launch a single Builder `Task`:
   - Prompt includes: builder protocol + task spec (with all enriched fields) + architecture snapshot (passed directly in the task description).
   - Builder reads/writes files. Does NOT call any MCP tools.
   - Returns: structured result summary (file path, action, public API, lint status).
3. **Coordinator stores** the result:
   ```
   store_memory(
     content=<builder result>,
     category="code",
     source_kind="summary",
     priority="normal",
     upsert_key="{repo}::e2e-build::{build_id}::phase-{N}-task-{T}-result",
     repo="{repo}",
     tags=["e2e-build", build_id]
   )
   ```
4. Use `model="fast"` for tasks with `model_hint="fast"` in the spec.

**1c. Review each phase**
After all tasks in a phase complete:
1. Read `agents/reviewer.md` from this skill folder.
2. Launch a single Reviewer `Task`:
   - Prompt includes: reviewer protocol + touched files list + phase spec + all builder result summaries from this phase (passed directly).
   - Returns: structured review report (PASS/FAIL + issues).
3. **Coordinator stores** the review:
   ```
   store_memory(
     content=<review report>,
     category="code",
     source_kind="summary",
     priority="normal",
     upsert_key="{repo}::e2e-build::{build_id}::review-phase-{N}",
     repo="{repo}",
     tags=["e2e-build", build_id]
   )
   ```
4. If FAIL: re-launch failing builder task with error context from the review report (max 3 retries per task).
5. If PASS: mark todos completed, advance to next phase.

**1d. Update progress**
After each phase completes:
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

### Phase 2: QA (QA Agent)

After all build phases complete:

1. Read `agents/qa.md` from this skill folder.
2. Launch a single `Task`:
   - Prompt includes: QA protocol + plan summary + progress summary + test baseline (all passed directly).
   - QA agent runs tests and checks. Does NOT call any MCP tools.
   - Returns: structured QA report (PASS/FAIL + blockers + warnings).
3. **Coordinator stores** the QA report:
   ```
   store_memory(
     content=<QA report>,
     category="decision",
     source_kind="summary",
     priority="high",
     upsert_key="{repo}::e2e-build::{build_id}::qa-report",
     repo="{repo}",
     tags=["e2e-build", build_id, "qa"]
   )
   ```
4. If FAIL:
   - Parse blocker list.
   - Launch targeted Builder agents to fix each blocker (with QA report content for context).
   - Re-run QA (max 2 total QA cycles).
5. If PASS (or max cycles exhausted): proceed to Phase 3.

### Phase 3: Completion

1. Store completion summary:
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
2. Present the user with a concise summary: what was built, test status, coverage, remaining issues.

## Memory Efficiency

Only the coordinator communicates with memory MCP. Subagents receive all context in their task prompt and return structured text.

- The coordinator persists subagent outputs immediately, then drops them from context.
- All tasks execute synchronously — one subagent at a time.
- The coordinator holds at most: `build_id`, `repo`, current phase/task, todo list, architecture snapshot, and the latest agent output.

## Context Window Discipline

- The coordinator NEVER reads source files. Agents read them directly.
- Phase specs are retrieved from memory one at a time, used for the current phase, then dropped.
- Agent return values are structured text (~100 lines max). Persisted and dropped before the next agent launches.

## Model Selection

- `model="fast"` for: tasks with `model_hint="fast"`, simple config edits.
- Default model for: QA agent, complex builder tasks, reviewer agent.

## Error Handling

- **Plan not found**: Tell the user to run `/e2e-plan` first. Halt.
- **Builder failure after 3 review retries**: Store failure, skip task, flag in QA.
- **QA failure after 2 cycles**: Complete with "partial success". Include all known issues.
- **All errors** stored in memory so they survive context window eviction.
