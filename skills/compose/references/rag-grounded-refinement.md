# RAG-Grounded Refinement

## Recommend When

- The output makes factual or methodological claims that must be checked against authoritative sources.
- A generator and a verifier should stay separate.
- Source-grounded revision is more important than subjective polish.

## Ask the User

- What sources should the evaluator verify against: local files/directories, web, or both?
- What kinds of claims or requirements should the evaluator check?
- Should the generator read the sources directly, or should grounding be evaluator-only?
- Is any methodology or source location intentionally hidden from the generator?
- What is the maximum round count? Default: `5`.

## Confirm Back

- Two agents: generator and evaluator.
- The source location(s) and verification focus.
- The tool split between generator and evaluator.
- If evaluator-only or hidden-methodology is requested, state separately what the generator may see and what only the evaluator may see.
- Exit condition: evaluator writes `output/evaluation-pass.flag` only when no material issues remain.

## Generate This Topology

- Generator node writes the primary artifact.
- Evaluator node depends on the generator and writes `output/evaluation-feedback.md`.
- Create one bipartite cycle:
  - `type`: `bipartite`
  - `producer`: generator
  - `evaluator`: evaluator
  - `max_rounds`: agreed limit
  - `exit_signal_file`: `output/evaluation-pass.flag`
- `final_output` is the generator's artifact.

## Agent Prompt Rules

### Generator

- Reads the task brief and the latest evaluator feedback, then revises the same artifact.
- On subsequent rounds, the generator must address every issue raised in the evaluator's feedback before rewriting.

### Evaluator

The evaluator prompt must instruct the evaluator to assess the artifact across two tiers, in order. Both tiers must be satisfied before the pass flag can be written.

**Tier 1 — Factual fidelity.** Every factual claim in the artifact is checked against the source corpus. Any claim that contradicts, misrepresents, softens an exact value with hedging language, or cannot be traced to the source is flagged as an error.

**Tier 2 — Source utilization and structural quality.** The evaluator checks whether the artifact demonstrates adequate engagement with the source material. Specifically:

- **Coverage**: Are there significant areas of the source corpus that the artifact ignores or barely touches? The evaluator should identify specific sections, concepts, or data from the sources that are absent from the artifact but relevant to the task.
- **Depth of synthesis**: Does the artifact merely restate source material in sequence, or does it integrate and connect ideas across source sections? Surface-level paraphrase of individual source passages, even if factually accurate, is insufficient when the task calls for a synthesized treatment.
- **Fitness for purpose**: Given the stated task, does the artifact actually serve that purpose? A technically accurate document can still fail if it is structured poorly for its audience, omits practical implications the sources support, or reads as a mechanical transcription rather than an authored work.

The evaluator prompt must instruct the evaluator to write specific, actionable feedback for every issue found in either tier — not just a label or status. Each issue should state what is wrong, where the relevant source material is, and what the generator should do differently.

#### Why Both Tiers Are Necessary

Compose should understand the failure mode this structure prevents: a competent generator will typically produce a first draft that is factually accurate — the source material is right in front of it, and modern LLMs are good at faithful extraction. If the evaluator only checks factual fidelity (Tier 1), it finds nothing wrong on round 1 and immediately writes the pass flag. The refinement cycle exits after a single round, producing an artifact that is correct but shallow. Tier 2 ensures the evaluator engages with whether the artifact is genuinely good, not just whether it avoids being wrong.

### Evaluator Pass Criteria

The evaluator prompt must state the pass criteria as a conjunction:

1. Zero factual errors remain (Tier 1 is clean).
2. No significant coverage gaps, synthesis weaknesses, or fitness-for-purpose problems remain (Tier 2 is clean).

The evaluator writes `output/evaluation-pass.flag` only when both conditions hold simultaneously. If Tier 1 is clean but Tier 2 has issues, the evaluator must not pass — it writes feedback and the cycle continues.

### Generating Effective Evaluator Prompts

When composing the evaluator's system prompt, apply these principles:

- **Make Tier 2 criteria concrete for the task.** Do not simply paste generic instructions about "coverage" and "synthesis." Translate them into task-specific questions. For a technical overview: "Does the overview explain how components X, Y, and Z interact, or does it just describe each in isolation?" For a methodology application: "Does the plan use the framework's own vocabulary and structural elements, or does it arrive at similar conclusions through parallel reasoning?"
- **Front-load the evaluator's obligation to find issues.** The evaluator's first action after reading should be identifying what is missing or weak, not confirming what is present. Structure the prompt so the evaluator inventories gaps before cataloging verified claims.
- **Require the evaluator to cite source locations for Tier 2 feedback.** When the evaluator says the artifact has a coverage gap, it must point to specific sections or passages in the source that should have been incorporated. This prevents vague feedback ("could be more thorough") that gives the generator nothing to work with.
- **Separate the evaluation from the pass decision.** The evaluator should complete its full written assessment before deciding whether to pass. Prompts that interleave assessment with the pass decision encourage premature closure — the evaluator starts confirming claims, builds momentum toward "everything checks out," and writes the pass flag before considering Tier 2.

## Hard Boundary for Evaluator-Only or Hidden-Methodology Setups

- The generator agent file must not mention the framework name, source path, corpus, source documentation, or methodology language anywhere.
- That boundary applies to both YAML frontmatter `description` and the markdown body.
- The generator should see only the visible artifact/task plus "revise from evaluator feedback."
- The evaluator alone gets the source path, retrieval instructions, hidden methodology, and pass criteria.
- Before launch, check the generated agent files and fix any leakage before proceeding.
