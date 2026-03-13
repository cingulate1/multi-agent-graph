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

## Generate This Topology

- Create one decomposer node that analyzes the task and defines assignments.
- If worker count is fixed, create that many worker nodes depending on the decomposer.
- If worker count is automatic, use a dynamic worker template so the decomposer can materialize workers at runtime.
- Workers write only their assigned outputs; no worker should depend on peer outputs.
- The final output may be a folder of worker artifacts or a manifest of produced files rather than a synthesized document.

## Agent Prompt Rules

- The decomposer must produce self-contained assignments with exact output filenames.
- Worker prompts should contain only the assigned subtask and required output path.
- Prefer cheaper or more mechanical models for workers unless the user overrides that choice.
- If the user really needs synthesis, add a separate downstream node or recommend a different pattern instead of smuggling synthesis into the workers.
