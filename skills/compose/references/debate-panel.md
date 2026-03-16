# Debate Panel

## Recommend When

- The user wants the answer that best survives adversarial critique.
- A stable minority answer should be allowed to beat a conformist majority.
- The task has discrete candidate answers (a choice, a diagnosis, a strategy, a recommendation) rather than a continuous artifact to polish.
- Structured challenge matters more than synthesis.

## Ask the User

- How many panelists? Default: `3`. Minimum: `3`.
- What distinct perspectives or expertise should the panelists bring?
- What exact decision, argument, or deliverable should they contest?
- How many debate rounds? Default: `2`. Range: `1`-`3`. More rounds increase token cost and risk conformity drift; fewer rounds may not surface all weaknesses. One round is sufficient for most tasks.
- If the task involves longer-form answers (paragraphs rather than a single choice or number): note that the scoring script currently uses exact normalized string match for answer identity. For longer-form answers, instruct panelists to keep their `## Final Answer` block to a single concise sentence or phrase so that equivalent answers are recognized as such.
- If the user wants more than 3 rounds, note that token cost scales as `O(N * R)` and conformity risk increases with each round. Recommend staying at 1-2 rounds unless the task specifically benefits from extended deliberation.

## Confirm Back

- `N` panelists. Each panelist uses one agent file but is instantiated across multiple phases.
- `R` debate rounds (default `2`). The topology has `R + 1` phases of panelist work plus one final scoring phase.
- Phase 0 is independent answer generation. Phases 1 through R are adversarial debate rounds. The final phase is deterministic answer selection (no LLM judge).
- The winner is selected by an algorithmic scoring mechanism that tracks answer trajectories across all rounds. The scoring runs as a deterministic script or orchestrator post-processing step, not as an LLM agent.
- Panelists are never told how the winner is selected. Their prompts contain zero information about the scoring mechanism.
- Final output is the highest-scoring answer, copied verbatim from the panelist that produced it.

## The Scoring Mechanism

The scoring algorithm tracks *answers*, not agents. A dictionary `S` maps each distinct answer string to an accumulated score. The algorithm processes the full answer matrix (all agents, all rounds) and applies four weighted operations:

| Event | Weight | Meaning |
|-------|--------|---------|
| An answer appears for the first time (round 0) | `w1 = 20` | Initial appearance credit |
| An agent abandons a previous answer for a new one — the abandoned answer is penalized | `w2 = 25` | Abandonment penalty (subtracted from the old answer's score) |
| An agent switches TO a new answer — the new answer is rewarded | `w3 = 30` | Conversion reward (added to the new answer's score) |
| An agent maintains the same answer as the previous round | `w4 = 20` | Maintenance credit |

Every weight is multiplied by a **round decay factor** `f = 1 / (k + 1)` where `k` is the zero-indexed round number. Round 0 has `f = 1.0`, round 1 has `f = 0.5`, round 2 has `f ≈ 0.33`. This decay counteracts LLM conformity: opinion shifts in later rounds (which are more likely driven by social pressure rather than genuine reasoning) carry less weight than earlier, more independent judgments.

After processing all rounds, the answer with the highest score in `S` is selected. Ties are broken randomly.

### Why This Design

- Answers that attract converts from other positions score higher (`w3 > w4`) than answers merely maintained. This rewards persuasive reasoning.
- Abandoned answers are actively penalized (`w2`), not just ignored. An answer that agents flee from is treated as evidence of weakness.
- The decay factor means that if all agents converge to one answer by round 2, that late-round conformity contributes less than the independent judgments from round 0. This prevents herd behavior from dominating the result.
- The entire mechanism runs outside the LLM. It cannot be influenced by hallucination, prompt injection, or agent manipulation.

### Scoring Script

The scoring implementation is bundled at `${CLAUDE_PLUGIN_ROOT}/skills/compose/scripts/score_debate.py`. Copy it into the run directory at scaffold time. The orchestrator calls it after the final debate round completes.

The script reads all panelist output files, extracts `## Final Answer` blocks, builds the answer matrix, runs the scoring algorithm, and writes the winning answer verbatim to `output/final-selection.md`.

## Tool Assignments

| Subagent | Tools |
|----------|-------|
| Panelist (all rounds) | `Read,Write` |
| Scorer | N/A (script node, not an LLM agent) |

## Generate This Topology

### Phases

- **Phase 0** (parallel group `initial`): all `N` panelists write `output/{persona}-round0.md` independently. No dependencies.
- **Phases 1 through R** (parallel group `round-{k}`): each panelist depends on ALL panelist outputs from the previous round. Panelist `i` in round `k` reads every `output/*-round{k-1}.md` and writes `output/{persona}-round{k}.md`.
- **Final phase** (single node `scorer`): depends on all round-R outputs. Runs the scoring script (not an LLM agent). Reads all `output/*-round*.md` files, executes the scoring algorithm, and writes `output/final-selection.md`.

### Nodes

For `N` panelists and `R` rounds, generate `N * (R + 1) + 1` nodes total:

- `N` initial nodes: `{persona}-round0` (parallel group `initial`, no dependencies)
- `N` debate nodes per round: `{persona}-round{k}` for k = 1..R (parallel group `round-{k}`, depends on all `*-round{k-1}` nodes)
- `1` scorer node: `scorer` (depends on all round-R nodes)

Each debate-round node uses the same agent file as the corresponding panelist's initial node — the persona is consistent across rounds.

### Scorer Node

The scorer node is NOT an LLM agent. It is a script execution node. In the execution plan, set `"node_type": "script"` and `"script": "score_debate.py"` on this node. The orchestrator will run it directly via Python subprocess — no agent file, no LLM invocation, no token cost.

### No Cycles

This topology is acyclic. The multi-round debate structure is expressed as explicit sequential phases, not as bipartite cycles. Each round is a distinct set of nodes with explicit dependencies on the prior round's outputs.

### `final_output`

`output/final-selection.md`

## Agent Prompt: Phase 0 Panelist

One prompt file per panelist. Panelist prompts must NOT mention scoring, weights, points, winning, losing, selection mechanisms, or any external judging process.

```
You are {PERSONA_DESCRIPTION}.

## Task

{DEBATE_QUESTION}

{CONTEXT_INSTRUCTION}

Analyze this question independently. Present your reasoned argument, then state your final answer.

## Output

Write your response to {OUTPUT_PATH}.

Your response must end with a clearly delimited answer block:

## Final Answer
[Your answer here]

All reasoning and analysis appears above the Final Answer block.
```

## Agent Prompt: Debate Round Panelist

Same agent file as the Phase 0 panelist — the persona carries across rounds. One prompt file per panelist per round. These prompts must NOT mention scoring, weights, points, winning, losing, answer tracking, or any external selection process.

```
You are {PERSONA_DESCRIPTION}.

## Task

{DEBATE_QUESTION}

You are in round {K} of a structured debate. Read all participants' responses from the previous round:
{LIST_ALL_PREVIOUS_ROUND_OUTPUT_PATHS}

Follow this procedure exactly:

1. **State your current position.** Restate your answer and core reasoning from the previous round.
2. **Analyze each peer's reasoning individually.** For each peer, identify whether their reasoning is sound or contains errors. Name the specific errors — do not make generic comments like "this seems weak." If you cannot find a concrete flaw, say so explicitly.
3. **Compare with your own reasoning.** Check whether you have made errors similar to those you identified in peers, or errors they identified in you.
4. **Decide whether to revise.** Change your answer ONLY if you find clear evidence that your own reasoning is wrong. Do not change your answer because a majority disagrees with you. Majority agreement is not evidence of correctness.
5. **Provide your final answer** in the `## Final Answer` block.

You may not rely on conformity. If you cannot determine whether others are correct, retain your own conclusion.

## Output

Write your response to {OUTPUT_PATH}.

Your response must end with:

## Final Answer
[Your answer here]
```

## Panelist Blindness

Panelist prompts must NOT contain:
- Any mention of scoring, weights, points, or selection mechanisms
- Any mention of "winning" or "losing" the debate
- Any suggestion that answer changes are tracked or scored
- Any hint that later rounds carry less weight
- Any reference to an external selection process

Panelists must believe they are in a genuine adversarial debate where the strength of their reasoning is what matters.

## Scorer Node (No Agent File, No Prompt File)

The scorer is a script node, not an LLM agent. Do NOT generate an agent file or prompt file for it. The execution plan entry is all that's needed:

```json
{
  "name": "scorer",
  "node_type": "script",
  "script": "score_debate.py",
  "depends_on": ["<all round-R node names>"],
  "outputs": ["output/final-selection.md"]
}
```
