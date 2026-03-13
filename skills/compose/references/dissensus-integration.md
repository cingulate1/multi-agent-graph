# Dissensus Integration

## Recommend When

- The user wants comprehensive coverage from multiple complementary lenses.
- Unique contributions matter more than overlap.
- Tension between perspectives should be integrated rather than eliminated.

## Ask the User

- How many panelists? Default: `3`.
- What distinct lens or perspective does each panelist bring?
- What final integrated artifact should the workflow produce?

## Confirm Back

- `N` complementary panelists plus `1` integrator.
- Panelists work independently; they are not refining each other.
- The integrator combines what is unique from each perspective rather than extracting consensus.

## Generate This Topology

- Phase 1: all panelists write `output/{persona}-initial.md` in parallel.
- Phase 2: the integrator depends on all panelist outputs, reads every `*-initial.md`, and writes the final integrated synthesis.

## Agent Prompt Rules

- Choose lenses that are genuinely different rather than redundant.
- Panelists should focus on what their lens sees that others might miss.
- Panelists do not need to read each other's work.
- The integrator should preserve useful tension, harvest unique contributions, and avoid collapsing everything into generic agreement.

