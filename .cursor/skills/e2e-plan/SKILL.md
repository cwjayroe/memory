---
name: e2e-plan
description: "Deep codebase exploration and implementation planning for a feature request. Produces a detailed, phased plan with enriched task specs stored in memory. Run this in Plan mode before invoking e2e-build to execute."
---

# E2E Plan

Explore the codebase deeply, then produce a structured implementation plan that builder agents can execute without re-discovering context. This skill runs in the main agent context (not delegated to a subagent) so it has the full context window for exploration.

The output is a complete plan stored in memory. After reviewing and approving, invoke `/e2e-build {build_id}` to execute it.

## Memory Key Schema

All plan artifacts are stored with deterministic upsert keys. The `{build_id}` is derived from the user's prompt (slugified first 40 chars + 6-char timestamp hash, e.g., `add-webhook-support-a3f2c1`).

| Artifact | Upsert Key | Category | Source Kind | Priority |
|----------|-----------|----------|-------------|----------|
| Input | `{repo}::e2e-build::{build_id}::input-doc` | documentation | reference | high |
| Codebase Analysis | `{repo}::e2e-build::{build_id}::codebase-analysis` | architecture | summary | high |
| Architecture Snapshot | `{repo}::e2e-build::{build_id}::architecture-snapshot` | architecture | summary | high |
| Plan | `{repo}::e2e-build::{build_id}::plan` | architecture | summary | high |
| Phase Specs | `{repo}::e2e-build::{build_id}::plan-phase-{N}` | architecture | summary | normal |
| Validation | `{repo}::e2e-build::{build_id}::plan-validation` | decision | summary | normal |

All writes use `upsert_key` for idempotency. All writes include `tags=["e2e-build", build_id]` and `repo="{repo}"`.

## Protocol

### Step 0: Initialize

1. Receive the user's prompt describing the feature to build.
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
4. Tell the user: `build_id = {build_id}`. They will need this to invoke the build step.

### Step 1: Search existing memory

Before exploring from scratch, check what's already known:

```
search_context(
  query="architecture patterns conventions {keywords from prompt}",
  categories=["decision", "architecture"],
  limit=6,
  ranking_mode="hybrid_weighted"
)
```

Look for: prior architecture decisions, existing conventions, previous builds in the same area, known constraints.

---

## Pass 1: Deep Exploration

The goal is to build a thorough, factual understanding of the codebase. Every claim in the plan must trace back to something discovered here. Do not skim — read actual file contents, trace actual call chains, extract actual code patterns.

### Step 2: Project structure

- List the project root and key directories (max 3 levels deep).
- Identify: language/framework, test framework, build system, package manager.

### Step 3: Integration path analysis

For each entry point or file the feature will touch:

1. **Read the file in full.** Document its public API: every exported function/class/constant with full signatures (parameter names, types, return types, default values).
2. **Trace imports outward**: What does this file import? Read those files. Build a chain until you reach leaf modules.
3. **Trace imports inward**: Use `Grep` to find every file that imports from this file. Record the specific names each importer uses.
4. **Map data flow**: Trace how data will move through the system for this feature. Document actual types at each boundary.

### Step 4: Pattern catalog

Extract **one concrete code example** (5-15 lines) for each distinct pattern builders will need:

- **Error handling**: try/except structure, error types, logging pattern.
- **Logging**: Logger initialization, level conventions, message format.
- **Configuration access**: How code reads config values.
- **Database/storage access**: ORM patterns, query patterns (if applicable).
- **Test structure**: Setup/teardown, assertion style, fixture usage.

For each pattern, record the source file, line range, and actual code.

### Step 5: Modification impact analysis

For each file that will be **modified** (not created):

1. **Current public API**: Every public function, class, constant with full signatures.
2. **Importers**: Every file that imports from it, with the specific names imported.
3. **Constraints**: What changes would break importers?
4. **Existing tests**: What behaviors are currently tested? What assertions would break?

### Step 6: Test pattern discovery

Read 2-3 existing test files to understand:
- Test file naming convention, class vs function style.
- Available fixtures (read `conftest.py` if it exists).
- Mocking patterns, assertion style.
- Record one complete test function as the **template test**.

### Step 7: High-risk files & gap analysis

**High-risk**: Files imported by 5+ others, files central to the integration path.

**Gaps**: What doesn't exist yet? New types, modules, config entries, test fixtures, dependencies.

### Step 8: Store codebase analysis

Store the complete exploration output:

```
store_memory(
  content=<codebase analysis report with all sections from Steps 2-7>,
  category="architecture",
  source_kind="summary",
  priority="high",
  upsert_key="{repo}::e2e-build::{build_id}::codebase-analysis",
  repo="{repo}",
  tags=["e2e-build", build_id, "codebase-analysis"]
)
```

---

## Pass 2: Specification

With the full codebase understanding in context, produce the plan. Every spec references concrete details from Pass 1 — no assumptions, no "follow existing patterns" without showing the pattern.

### Step 9: Architecture snapshot

Store a concise architecture summary:

```
store_memory(
  content=<architecture summary>,
  category="architecture",
  source_kind="summary",
  priority="high",
  upsert_key="{repo}::e2e-build::{build_id}::architecture-snapshot",
  repo="{repo}",
  tags=["e2e-build", build_id]
)
```

Content: directory structure, frameworks, integration points, reusable utilities (with paths and signatures), prior decisions, test patterns (with template test reference), high-risk files, caller map.

### Step 10: Produce the phased plan

Decompose the feature into ordered implementation phases. Each phase contains tasks that can execute sequentially and must complete before the next phase starts.

**Phase ordering — adapt to the project:**

For **greenfield** builds:
1. Foundation (models, schemas, types, config)
2. Core (business logic, services)
3. Integration (routes, CLI, API endpoints)
4. Polish (edge cases, validation, exports)

For **existing system** builds:
1. Extend models (safe additions — no existing callers affected)
2. New modules (isolated new files)
3. Wire in (modify existing files — highest risk)
4. Tests (new + updated)
5. Polish (config, exports, edge cases)

**Risk-aware rules:**
- High-risk files modified as late as possible.
- Create new files before modifying files that import them.
- Group modifications to the same file in one task.
- Max 8 phases total.

**For each task, produce the full enriched spec:**

```yaml
- task_type: "create" | "modify"
  file_path: absolute path
  description: one-line summary
  high_risk: true | false

  # For modify tasks only (from Step 5)
  existing_api: |
    <Full public API with signatures>
    <Caller count>

  # What must NOT change (from Step 5)
  preserve:
    - "<signature or behavior> — reason"

  # Detailed implementation spec
  spec: |
    - Function/class signatures with types
    - Behavior requirements and edge cases
    - Error handling expectations
    - Integration points

  # Cross-task contracts
  interface_contract:
    produces:
      - "<exported name with full signature> — consumed by <file> in Phase N"
    consumes:
      - "<import statement> — produced by <file> in Phase N Task M"
    types_shared_with:
      - "<file that must use same type definitions>"

  # Actual code to follow (from Step 4)
  pattern_reference: |
    # <Pattern name> from <file>:<lines>
    <5-15 lines of actual code>

  # Test plan (from Step 6)
  test_strategy: |
    test_file: <path> (exists | to create)
    template_test: <test function> at <file>:<line>
    scenarios:
      - <scenario> -> <expected outcome>
    mocking: <what to mock, based on existing patterns>
    fixtures: <existing fixtures to use>

  depends_on: [file paths that must exist first]
  test_file: path to test file
  model_hint: "fast" (for simple edits) or omit
```

**Field requirements:**

| Field | create | modify |
|-------|--------|--------|
| `existing_api` | omit | required |
| `preserve` | omit | required |
| `spec` | required | required |
| `interface_contract` | if others depend on this | if others depend on this |
| `pattern_reference` | required | if follows a repeating pattern |
| `test_strategy` | required | required |

### Step 11: Store plan and phase specs

**Top-level plan**:
```
store_memory(
  content=<plan with summary, interface contracts, phases, assumptions>,
  category="architecture",
  source_kind="summary",
  priority="high",
  upsert_key="{repo}::e2e-build::{build_id}::plan",
  repo="{repo}",
  tags=["e2e-build", build_id]
)
```

Plan content structure:
```
# Build Plan: {build_id}

## Summary
<2-3 sentence overview>

## Interface Contracts
<Every cross-task boundary: produces/consumes/types_shared_with>

## Phases
- Phase 1: {name} — {count} tasks ({files})
- Phase 2: {name} — {count} tasks ({files})
...

## Assumptions
<Ambiguities resolved, assumptions made>

## Total: {phases} phases, {tasks} tasks
```

**Per-phase specs** — one per phase:
```
store_memory(
  content=<full enriched task specs for phase N>,
  category="architecture",
  source_kind="summary",
  priority="normal",
  upsert_key="{repo}::e2e-build::{build_id}::plan-phase-{N}",
  repo="{repo}",
  tags=["e2e-build", build_id, "phase-{N}"]
)
```

---

## Pass 3: Validation

### Step 12: Self-validate the plan

Before presenting to the user, check:

1. **Dependency graph**: Every `depends_on` points to a file created in an earlier phase or already existing. No cycles.
2. **Interface contracts**: Every `consumes` has a matching `produces` in an earlier phase. Signatures match.
3. **Completeness**: Every requirement from the user prompt maps to at least one task.
4. **File conflicts**: No two tasks in the same phase modify the same file.
5. **Preservation**: No task's `spec` contradicts another's `preserve` list.
6. **Test coverage**: Every non-trivial task has a `test_strategy`.

If issues found: fix them in the plan and re-store the corrected phase specs.

Store the validation result:
```
store_memory(
  content=<validation report: PASS + any warnings>,
  category="decision",
  source_kind="summary",
  priority="normal",
  upsert_key="{repo}::e2e-build::{build_id}::plan-validation",
  repo="{repo}",
  tags=["e2e-build", build_id, "validation"]
)
```

### Step 13: Present to user

Show the user:
- **Plan summary**: phases, task counts, files
- **Interface contracts**: cross-task boundaries
- **Assumptions**: anything ambiguous that was resolved
- **Validation**: PASS/warnings
- **Next step**: `Approve this plan, then run /e2e-build {build_id} to execute.`

## Constraints

- Do not implement anything. Planning only — do not write or edit project files.
- Do not hallucinate file paths. Use actual paths discovered during exploration.
- Do not produce more than 8 phases.
- Do not write vague specs. Every `spec` must be concrete enough for a builder to implement without reading additional files.
- Do not skip the codebase analysis. It is the factual foundation for everything.
- Every `interface_contract.consumes` must have a matching `produces` in an earlier phase.
- Prefer reusing existing functions and utilities over creating new ones.
- Do not create tasks for documentation unless the user explicitly requests them.
