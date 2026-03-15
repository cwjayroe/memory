---
name: orchestrate-plan
description: Orchestrate multi-phase implementation plans by loading context into memory, decomposing work into parallel batches, delegating to specialist agents (creator, integrator, verifier), and tracking progress via todos. Use when executing a plan file, implementing a multi-step feature across many files, or when the user asks to "orchestrate", "build this plan", "delegate tasks", or coordinate complex multi-file changes. Also use when the user wants to reduce context window load by offloading work to subagents.
---

# Orchestrate Plan

Coordinate execution of multi-phase plans by delegating to specialist agents while keeping the orchestrator's context lean.

## Agents

This skill bundles three specialist agent definitions. Read them and include their instructions in subagent `Task` prompts.

- **Creator** (`agents/creator.md`): For new file creation from a spec.
- **Integrator** (`agents/integrator.md`): For modifying existing files.
- **Verifier** (`agents/verifier.md`): For post-batch verification.

## Execution Protocol

### 1. Load the plan

Read the plan source (plan file, user prompt, or prior conversation context). Extract: phases, task list, dependency order, files to create, files to modify.

### 2. Store context in memory

Persist two structured memories via the memory MCP:

**Architecture snapshot** (current state):
- `category="architecture"`, `source_kind="summary"`, `priority="high"`
- `upsert_key="{repo}::architecture-snapshot-pre-{plan_name}"`
- Content: key files, current bottlenecks, relevant data structures, integration points.

**Plan overview** (what will be built):
- `category="architecture"`, `source_kind="summary"`, `priority="high"`
- `upsert_key="{repo}::plan-overview-{plan_name}"`
- Content: all phases summarized, schemas, new capabilities, files to create/modify.

### 3. Initialize todos

Create a todo for each discrete task. Mark the first batch `in_progress`.

### 4. Decompose into parallel batches

Classify each task as **Creator** or **Integrator**.

Dependency rules:
- A file must exist before another file can import from it.
- Independent Creator tasks can run in parallel.
- Independent Integrator tasks can run in parallel if they touch different files.
- Cross-phase tasks are sequential unless explicitly independent.

Max 3 subagents per batch (leave headroom for verification).

### 5. Delegate each batch

For each task, launch a `Task` with `subagent_type="generalPurpose"`:

**Creator tasks:**
1. Read `agents/creator.md` from this skill folder.
2. Build prompt: creator protocol + file spec (path, signatures, schema) + list of sibling files in target directory.

**Integrator tasks:**
1. Read `agents/integrator.md` from this skill folder.
2. Build prompt: integrator protocol + full current file content + edit instructions + dependent file paths.

Do NOT read full file contents into the orchestrator's context. Include file paths in the subagent prompt and instruct the subagent to read them.

### 6. Verify each batch

After all subagents in a batch return:
1. Read `agents/verifier.md` from this skill folder.
2. Launch a verification `Task` with the verifier protocol and the list of all files touched in this batch.
3. If FAIL: re-launch the failing task with the error context appended.
4. If PASS: mark todos `completed`, advance to next batch.

### 7. Advance and repeat

Update todos after each batch. Launch the next batch immediately. Continue until all todos are `completed`.

### 8. Capture completion

Store a completion summary in memory:
- `category="decision"`, `source_kind="summary"`, `priority="high"`
- `upsert_key="{repo}::completion-summary-{plan_name}"`
- Content: new files created, files modified, new capabilities added, key architectural changes.

## Context Window Discipline

- Never read a file just to pass it to a subagent. Include the path and instruct the subagent to read it.
- Only read files in the orchestrator when verifying a specific integration point or when the file is under 30 lines.
- Store plan details in memory rather than holding them in conversation context.
- One task per subagent, explicit deliverable, explicit file path.

## Model Selection

- `model="fast"` for: config edits, small targeted modifications, single-method additions.
- Default model for: new file creation with complex specs, multi-method integrations, cross-file reasoning.
