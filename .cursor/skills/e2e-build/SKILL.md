---
name: e2e-build
description: End-to-end project build from a feature request. Accepts a prompt describing what to build, plans the implementation, builds it via sequential delegated agents, and QAs the result. The coordinator handles all memory persistence and direction of the work.
---

# E2E Build

Accept a feature request from the user's prompt. Plan it, build it, QA it. The coordinator is the single process that communicates with the memory MCP — subagents are pure computation that receive context in their task prompt and return structured output.

## Agents

This skill bundles five purpose-built agents. None of them call MCP tools — they receive all context in the task description and return structured output to the coordinator.

- **Planner** (`agents/planner.md`): Two-pass analysis — deep codebase exploration then detailed specification. Returns codebase analysis, architecture snapshot, and phased plan with enriched task specs (interface contracts, pattern references, test strategies).
- **Plan Validator** (`agents/plan-validator.md`): Lightweight validation of the plan before building. Checks dependency graph, interface contract alignment, completeness, and file conflicts.
- **Builder** (`agents/builder.md`): Creates new files or modifies existing ones → returns result summary.
- **Reviewer** (`agents/reviewer.md`): Per-phase correctness review including spec compliance, interface contract validation, and cross-file consistency → returns review report.
- **QA** (`agents/qa.md`): End-to-end quality assurance — tests, coverage, lint, imports, completeness audit → returns QA report.

## Memory Key Schema

All inter-phase state is persisted to memory MCP by the coordinator using deterministic upsert keys. The `{build_id}` is derived from the user's prompt (slugified first 40 chars + 6-char timestamp hash, e.g., `add-webhook-support-a3f2c1`).

| Phase | Upsert Key | Category | Source Kind | Priority |
|-------|-----------|----------|-------------|----------|
| Input | `{repo}::e2e-build::{build_id}::input-doc` | documentation | reference | high |
| Plan | `{repo}::e2e-build::{build_id}::codebase-analysis` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::architecture-snapshot` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::plan` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::plan-phase-{N}` | architecture | summary | normal |
| Plan | `{repo}::e2e-build::{build_id}::plan-validation` | decision | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::phase-{N}-task-{T}-result` | code | summary | normal |
| Build | `{repo}::e2e-build::{build_id}::progress` | architecture | summary | high |
| Review | `{repo}::e2e-build::{build_id}::review-phase-{N}` | code | summary | normal |
| QA | `{repo}::e2e-build::{build_id}::qa-report` | decision | summary | high |
| Baseline | `{repo}::e2e-build::{build_id}::test-baseline` | code | summary | high |
| Done | `{repo}::e2e-build::{build_id}::completion` | decision | summary | high |

All writes use `upsert_key` for idempotency. All writes include `tags=["e2e-build", build_id]` and `repo="{repo}"`.

## Execution Protocol

### Phase 0: Accept & Initialize

1. Receive the user's prompt describing the feature to build. No formal document required — the prompt IS the feature spec.
2. Derive `build_id`: slugify the first 40 chars of the prompt + 6-char hash of current timestamp.
3. Store the prompt in memory:
   ```
   store_memory(
     content=<user prompt>,
     category="documentation",
     source_kind="reference",
     priority="high",
     upsert_key="{repo}::e2e-build::{build_id}::input-doc",
     repo="{repo}",
     tags=["e2e-build", build_id]
   )
   ```
4. **Capture pre-build test baseline** (for existing systems):
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
5. Retain `build_id`, `repo`, and the full prompt text for the planner.

### Phase 1: Plan (Planner Agent + Validation)

**1a. Launch planner**

1. Read `agents/planner.md` from this skill folder.
2. Optionally, retrieve prior architectural context for the planner:
   ```
   search_context(
     query="architecture patterns conventions {keywords from prompt}",
     categories=["decision", "architecture"],
     limit=6,
     ranking_mode="hybrid_weighted"
   )
   ```
   If results are returned, include them in the planner's task prompt as prior context.
3. Launch a single `Task` with `subagent_type="generalPurpose"`:
   - Prompt includes: planner protocol + **the full user prompt** (passed directly) + repo name + any prior context from step 2.
   - The planner does NOT call any MCP tools. It works in two passes:
     - **Pass 1 — Deep Exploration**: Reads actual file contents, traces call chains, extracts code patterns, analyzes modification impact, discovers test patterns.
     - **Pass 2 — Specification**: Using the exploration results, produces architecture snapshot, phased plan with enriched task specs (including `existing_api`, `preserve`, `interface_contract`, `pattern_reference`, `test_strategy`).
   - Returns structured text delimited by markers: `===CODEBASE_ANALYSIS===`, `===ARCHITECTURE_SNAPSHOT===`, `===PLAN===`, `===PHASE_N===`, `===SUMMARY===`.
4. **Coordinator persists** the planner's output using `bulk_store`:
   ```
   bulk_store(
     project_id=<active_scope>,
     memories=[
       { content: <codebase analysis>, category: "architecture", source_kind: "summary", priority: "high", upsert_key: "{repo}::e2e-build::{build_id}::codebase-analysis", repo: "{repo}", tags: ["e2e-build", build_id, "codebase-analysis"] },
       { content: <architecture snapshot>, category: "architecture", source_kind: "summary", priority: "high", upsert_key: "{repo}::e2e-build::{build_id}::architecture-snapshot", repo: "{repo}", tags: ["e2e-build", build_id] },
       { content: <plan>, category: "architecture", source_kind: "summary", priority: "high", upsert_key: "{repo}::e2e-build::{build_id}::plan", repo: "{repo}", tags: ["e2e-build", build_id] },
       { content: <phase 1 spec>, category: "architecture", source_kind: "summary", priority: "normal", upsert_key: "{repo}::e2e-build::{build_id}::plan-phase-1", repo: "{repo}", tags: ["e2e-build", build_id, "phase-1"] },
       ...
     ]
   )
   ```
5. Parse the planner's `===SUMMARY===` section. Initialize todos from phase summaries.

**1b. Validate plan**

1. Read `agents/plan-validator.md` from this skill folder.
2. Launch a single `Task` with `subagent_type="generalPurpose"` and `model="fast"`:
   - Prompt includes: validator protocol + plan content + all phase spec contents + architecture snapshot (all passed directly).
   - The validator does NOT call any MCP tools.
   - Returns structured text with `===VALIDATION_REPORT===` marker.
3. **Coordinator stores** the validation report:
   ```
   store_memory(
     content=<validation report>,
     category="decision",
     source_kind="summary",
     priority="normal",
     upsert_key="{repo}::e2e-build::{build_id}::plan-validation",
     repo="{repo}",
     tags=["e2e-build", build_id, "validation"]
   )
   ```
4. If FAIL: re-launch planner with the validation report as additional context (max 1 correction cycle). If still FAIL after correction: surface issues to user and halt.

**1c. Approval gate** (default: pause for review)

Present the user with:
- Plan summary (phases, task counts, file lists)
- Interface contracts (cross-task boundaries)
- Assumptions and ambiguities flagged by the planner
- Validation result (PASS/FAIL and any warnings)

Wait for user confirmation before proceeding to Phase 2.

**Opt-out**: If the user's prompt contains keywords like "just build it", "autonomous", "no approval", or "skip review": proceed directly to Phase 2 without pausing.

### Phase 2: Build (Builder Agent - Sequential Execution)

For each phase N (sequential phases, sequential tasks within):

**2a. Parse phase spec**
- Extract the phase spec from the planner's output (already stored in memory and available in coordinator context from the bulk_store).
- Read ONLY the task list and file paths. Do NOT read source files.

**2b. Execute tasks sequentially**
For each task T in the phase (**one at a time**):
1. Read `agents/builder.md` from this skill folder.
2. Launch a single Builder `Task`:
   - Prompt includes: builder protocol + task spec + architecture snapshot (passed directly in the task description).
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

**2c. Review each phase**
After all tasks in a phase complete:
1. Read `agents/reviewer.md` from this skill folder.
2. Launch a single Reviewer `Task`:
   - Prompt includes: reviewer protocol + touched files list + phase spec + all builder result summaries from this phase (passed directly in the task description).
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
4. If FAIL: re-launch failing builder task with error context from the review report (max 3 retries per task). Coordinator stores retry results.
5. If PASS: mark todos `completed`, advance to next phase.

**2d. Update progress**
After each phase completes, the coordinator upserts progress:
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
2. Launch a single `Task`:
   - Prompt includes: QA protocol + plan summary + progress summary + test baseline (all passed directly in the task description).
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
   - Parse blocker list from the QA return.
   - Launch targeted Builder agents to fix each blocker (with QA report content in the task description for context).
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
2. Present the user with a concise summary: what was built, test status, coverage, remaining issues.

## Memory Efficiency

Only the coordinator process communicates with the memory MCP. This eliminates subagent MCP connections and prevents the accumulation of server processes / model loads.

- Subagents receive all context in their task prompt. They do NOT call `search_context`, `store_memory`, `get_memory`, or any other MCP tool.
- The coordinator persists all subagent outputs immediately after receiving them, then drops the output from context.
- All tasks execute synchronously — one subagent at a time — to prevent parallel MCP connection spawning.

## Context Window Discipline

- The coordinator NEVER reads source files. Agents read them directly.
- The user's prompt is stored in memory by the coordinator and also passed directly to the planner. After the planner returns, the coordinator drops the prompt from context.
- Phase specs are returned by the planner as structured text. The coordinator persists them and retains only the task list (file paths + one-line descriptions).
- Agent return values are structured text (~100 lines max). The coordinator persists them to memory and drops them before launching the next agent.
- The coordinator holds at most: `build_id`, `repo`, current phase/task number, todo list, and the latest agent output (persisted and dropped before the next agent launches).

## Model Selection

- `model="fast"` for: tasks with `model_hint="fast"`, simple config edits.
- Default model for: planner agent, QA agent, complex builder tasks, reviewer agent.

## Error Handling

- **Planner failure**: Surface error to user. Do not proceed to build.
- **Builder failure after 3 review retries**: Store failure in memory, skip task, flag it in QA phase.
- **QA failure after 2 cycles**: Complete with "partial success" status. Include all known issues in the completion summary.
- **All errors** are stored in memory by the coordinator so they survive context window eviction.
