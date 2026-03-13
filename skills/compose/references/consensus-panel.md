# Consensus Panel

## Recommend When

- The user wants real common ground across distinct perspectives.
- Overlap is the signal being extracted.
- Unresolved disagreement should be filtered out rather than preserved.

## Ask the User

- How many panelists? Default: `3`.
- Who is each panelist as a persona or worldview?
- What shared question or deliverable should all panelists address?

## Confirm Back

- `N` distinct personas, not interchangeable roles.
- `2N+1` agents total: `N` initial panelists, `N` refinement panelists, `1` synthesizer.
- Final output is a consensus synthesis, not a vote tally and not a catalog of all views.

## Generate This Topology

- Phase 1: all panelists write `output/{persona}-initial.md` in parallel.
- Phase 2: all refinement panelists depend on all Phase 1 outputs, read every `*-initial.md`, and write `output/{persona}-refine.md` in parallel.
- Phase 3: the synthesizer depends on all refined outputs, reads every `*-refine.md`, and writes the final synthesis.

## Agent Prompt Rules

- Define panelists by who they are, not by generic job labels.
- Phase 1 agents should produce independent first-pass answers from their own perspective.
- Phase 2 agents should update where genuinely persuaded while still maintaining their persona.
- The synthesizer should extract convergence only. Remaining divergence can be noted briefly, but it should not drive the final output.

