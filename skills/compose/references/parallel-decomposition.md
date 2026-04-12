# Parallel Decomposition

## Recommend When

- The task can be partitioned into independent assignments.
- Worker outputs do not need within-pattern reconciliation.
- The main value is throughput or coverage, not debate or consensus.

## Ask the User

- Should the decomposition be user-specified or decided by a decomposer agent?
- Is the worker count fixed or should the decomposer decide automatically?
- What should each worker produce?
- Is downstream synthesis intentionally out of scope, or should that be handled later by another pattern?

## Confirm Back

- One decomposer plus either a fixed worker set or a dynamic worker template.
- Workers are independent and unaware of each other.
- Outputs are collected, not synthesized, unless a separate downstream step is added.

## Tool Assignments

| Subagent | Tools |
|----------|-------|
| Decomposer | `Read,Write` |
| Worker | `Read,Write` |

## Generate This Topology

- Create one decomposer node that analyzes the task and defines assignments.
- If worker count is fixed, create that many worker nodes depending on the decomposer.
- If worker count is automatic, use a dynamic worker template so the decomposer can materialize workers at runtime.
- Workers write only their assigned outputs; no worker should depend on peer outputs.
- The final output may be a folder of worker artifacts or a manifest of produced files rather than a synthesized document.

`final_output`: Set to `output/assignments.json` (the manifest). The individual worker outputs are referenced within it.

## Agent Prompt Templates

Note: Every template below ends with the validator-enforced line `Write your output to {ABSOLUTE_OUTPUT_PATH}`. Substitute only the path placeholder; preserve the rest verbatim. See SKILL.md "Mandatory Final Line" for the full rule. The decomposer's `ABSOLUTE_OUTPUT_PATH` should resolve to the run's `output/assignments.json`; each worker's resolves to its own `output/{identifier}.md`.

## Agent Prompt: Decomposer

```
## Task

{TASK_DESCRIPTION}

{CONTEXT_INSTRUCTION}

Break this task into independent assignments that can be executed in parallel. For each assignment, specify:
- A short identifier (used as the worker's name)
- The specific subtask to perform
- The exact output filename: output/{identifier}.md

## Output

A JSON assignment manifest in this format:

[
  {
    "name": "{identifier}",
    "task": "{subtask description}",
    "output": "output/{identifier}.md"
  }
]

Write your output to {ABSOLUTE_OUTPUT_PATH}
```

## Agent Prompt: Worker

One prompt file per worker. Workers should contain only their assigned subtask.

```
## Task

{ASSIGNED_SUBTASK}

{CONTEXT_INSTRUCTION}

## Output

{OUTPUT_FORMAT}

Write your output to {ABSOLUTE_OUTPUT_PATH}
```

## Agent Prompt: Deletion Worker

When a worker's job is to delete files rather than produce artifacts (e.g., triaging a batch and removing files that fail a criterion), it writes a **deletion token** instead of a standard output. The execution plan declares its output as a `.temp` file (e.g., `output/{identifier}-deletions.temp`), and the orchestrator verifies every claimed deletion on completion.

The prompt validator enforces the same `Write your output to` final line — the path just points to the `.temp` file.

```
## Task

{ASSIGNED_SUBTASK}

{CONTEXT_INSTRUCTION}

## Procedure

For each file in your batch:
1. Read the file.
2. {EVALUATION_CRITERIA}
3. If the file fails the criteria, delete it with the Bash tool, then record the deletion.
4. If the file passes, move on to the next file.

## Output

A deletion token listing every file you deleted, one per line, in this exact format:

"{ABSOLUTE_PATH_OF_DELETED_FILE}" was deleted

If you deleted no files, write an empty file.

Write your output to {ABSOLUTE_OUTPUT_PATH}
```
