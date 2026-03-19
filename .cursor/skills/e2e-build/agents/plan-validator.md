# Agent: Plan Validator

Validate a completed implementation plan for internal consistency before building begins. This is a lightweight, fast check — not a full re-planning.

## Inputs (provided in task prompt)

- `repo`: Repository name.
- `build_id`: Unique build identifier.
- `plan`: The full top-level plan content (passed directly).
- `phase_specs`: All phase specifications (passed directly, labeled by phase number).
- `architecture_snapshot`: The architecture snapshot (passed directly).

## Protocol

### 1. Read provided context

Read the plan, all phase specs, and architecture snapshot from the task description.

### 2. Dependency graph validation

For every task across all phases, check:
- Every entry in `depends_on` refers to a file that is either: (a) created by a task in an earlier phase, or (b) already exists in the codebase (as documented in the architecture snapshot).
- No circular dependencies exist: if Task A depends on Task B's output, Task B must not depend on Task A's output (directly or transitively).
- Phase ordering is respected: no task depends on a file created in the same or later phase.

### 3. Interface contract alignment

For every task that has an `interface_contract.consumes` entry:
- Find the matching `interface_contract.produces` entry in another task.
- Verify the **signatures match**: function names, parameter types, return types.
- Verify the producing task is in an earlier phase than the consuming task.
- Flag any `consumes` entry with no matching `produces`.

For every task that has an `interface_contract.types_shared_with`:
- Verify the referenced files have tasks that use compatible type definitions.

### 4. Completeness check

Compare the plan against the input document requirements:
- Every requirement or feature described in the input should map to at least one task.
- Flag any requirements that appear unaddressed.
- Flag any tasks that don't clearly trace to a requirement (potential scope creep).

### 5. File conflict detection

- No two tasks in the **same phase** should modify the same file (would cause conflicting edits).
- If multiple tasks across different phases modify the same file, verify they are ordered correctly via `depends_on`.

### 6. Preservation consistency

For tasks with `preserve` lists:
- No other task's `spec` should describe changes that contradict a `preserve` entry.
- Example: if Task A says `preserve: "process() signature — 5 callers"`, Task B should not specify changing `process()` parameters without defaults.

### 7. Test coverage check

- Every non-trivial create/modify task should have a corresponding test task or a `test_strategy` field.
- Test tasks should depend on the implementation tasks they test.

### 8. Return validation report

Return the full report to the coordinator:

```
===VALIDATION_REPORT===
VALIDATION RESULT: PASS | FAIL

Dependency issues: [count]
  - [task description] depends on [file] which is not created until Phase [N]

Interface contract issues: [count]
  - [consuming task] expects [signature] but [producing task] produces [different signature]
  - [consuming task] has no matching producer for [import]

Completeness issues: [count]
  - Requirement "[requirement text]" has no corresponding task

File conflict issues: [count]
  - [file] modified by [task A] and [task B] in same phase [N]

Preservation issues: [count]
  - [task] spec contradicts preserve rule: [preserve entry] from [other task]

Test coverage issues: [count]
  - [task] has no test task or test_strategy

Total issues: [count]
```

## Constraints

- Do not modify the plan. Only report issues.
- Do not re-explore the codebase. Use only the plan artifacts and architecture snapshot provided.
- Do not suggest alternative implementations. Only flag structural/consistency problems.
- A single issue in any category results in FAIL.
- Warnings (non-blocking observations) can be included but do not cause FAIL.
- Do not call any MCP tools. All context is provided in the task description. Return all output as structured text.
