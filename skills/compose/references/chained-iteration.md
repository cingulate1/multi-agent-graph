# Chained Iteration

## Recommend When

- One agent can do the work.
- Success is objectively self-checkable.
- The likely failure mode is missing a concrete constraint on the first pass.

Use a different pattern if quality is subjective (`rubric-based`), facts need source verification (`rag-grounded`), or multiple perspectives matter (panel patterns).

## Ask the User

- What exact constraint must the output satisfy?
- How can Claude verify that constraint mechanically?
- What is the maximum iteration count? Default: `3`.

## Confirm Back

- One writer/refiner agent.
- One primary output artifact.
- Self-loop up to the agreed iteration limit.
- Exit condition: the agent writes `output/constraint-met.flag` only when the constraint is satisfied.

## Generate This Topology

- Create one node with no dependencies.
- Create one self-loop cycle:
  - `type`: `self-loop`
  - `agent`: the writer/refiner node
  - `max_iterations`: agreed limit
  - `exit_signal_file`: `output/constraint-met.flag`
- `final_output` is the primary artifact written by that node.

## Agent Prompt Rules

- Tell Claude to read `output/` for any prior draft and the current iteration number.
- Tell Claude to produce or refine the same artifact on every iteration.
- Require an explicit self-check against the constraint before each stop.
- Tell Claude to make surgical revisions instead of replacing good content wholesale.

