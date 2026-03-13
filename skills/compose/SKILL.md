---
name: multi-agent-graph-compose
description: "Guides the user through selecting and configuring a multi-agent execution pattern for their task. Triggers when the user invokes /multi-agent-graph:run."
---

# Multi-Agent Graph: Compose

You are guiding the user through setting up a multi-agent execution pattern for their task. This is a Socratic exchange — ask questions, make recommendations, and confirm before proceeding.

## Reference Load Map

Read only the reference for the active pattern. If the user is choosing between two close options, you may read those candidate references and no others.

- Chained Iteration → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/chained-iteration.md`
- RAG-Grounded Refinement → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/rag-grounded-refinement.md`
- Rubric-Based Refinement → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/rubric-based-refinement.md`
- Consensus Panel → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/consensus-panel.md`
- Debate Panel → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/debate-panel.md`
- Dissensus Integration → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/dissensus-integration.md`
- Parallel Decomposition → `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/parallel-decomposition.md`

When you begin writing agent files, also read `${CLAUDE_PLUGIN_ROOT}/skills/compose/references/subagents.md`. Use it for subagent prompt scope, frontmatter, and what generated agents can and cannot assume.

## Exchange Flow

### Step 1: Understand the Task

Ask the user what they want accomplished. Listen for signals about:
- Whether the task has a single clear answer or multiple valid perspectives
- Whether output quality is subjective or can be objectively verified
- Whether the work can be parallelized
- Whether iterative refinement is needed

If the user already described their task when invoking the command, skip this step and move to pattern recommendation.

### Step 2: Recommend a Pattern

Recommend based on task characteristics:

| Signal | Recommended Pattern |
|--------|-------------------|
| Output must meet a measurable constraint | Chained Iteration |
| Claims need verification against sources | RAG-Grounded Refinement |
| Quality is subjective, multi-dimensional | Rubric-Based Refinement |
| Want agreement across perspectives | Consensus Panel |
| Want the most robust/defensible answer | Debate Panel |
| Want comprehensive multi-perspective coverage | Dissensus Integration |
| Work decomposes into independent pieces | Parallel Decomposition |

Present your recommendation with a brief explanation of WHY this pattern fits. Also mention 1-2 alternatives the user might consider. Let the user confirm or choose differently.

Once a pattern is selected or clearly favored, immediately read its reference from the load map above. Use that reference as the source of truth for:
- what pattern-specific questions to ask next
- which agents/phases the workflow requires
- which agent should read which files
- what cycle or parallel structure to generate
- what pattern-specific prompt boundaries must be enforced

### Step 3: Configure the Pattern

Ask only the minimum pattern-specific questions required by the active reference. Be conversational, not interrogative. Suggest defaults where appropriate. Do not improvise pattern-specific topology or agent-behavior rules from memory; follow the active reference.

### Step 4: Model Selection

For most patterns, default to:
- **Opus**: All reasoning-heavy agents (panelists, evaluators, synthesizers, generators, integrators, selectors)
- **Sonnet**: Mechanical/structured agents (workers in Parallel Decomposition)

Ask the user if they want to override any model choices.

### Step 5: Tools

Ask what tools the agents will need. Defaults:
- Read, Write, Glob, Grep — almost always needed
- WebSearch, WebFetch — if the task involves external information
- Bash — if the task involves running code or scripts

### Step 6: Confirm

Summarize the full configuration concisely:
- Task description
- Pattern chosen
- Agent count / topology
- Pattern-specific settings from the active reference
- Model selections
- Tools

Ask the user to confirm. If they want changes, go back to the relevant step.

## After Confirmation

Once the user confirms, re-read the active reference and proceed to **generation**. Do NOT ask more questions — execute the following steps:

### Generate Run Directory

Create the run directory:
```
{PLUGIN_ROOT}/runs/{YYMMDD}_{slug}/
  output/
  agents/
  logs/
```

Where `{slug}` is a short kebab-case summary of the task (max 40 chars).

### Write config.json

Write the full configuration to `{run_dir}/config.json`. Include all details from the exchange.

### Generate Agent Files

Write agent `.md` files to `{run_dir}/agents/`. Each agent file must have:
- YAML frontmatter: `name`, `description`, `tools` (comma-separated), `model`
- Markdown body: the system prompt

Agent prompts must:
- State the agent's role and task clearly
- Specify exactly what files to read (inputs) and write (outputs)
- Include a STOP boundary: "Do NOT simulate or perform the role of any other agent"
- Reference the run directory for all file paths: use relative paths from the run dir

Use the active reference to determine:
- agent names, phases, and responsibilities
- node dependencies and parallel groups
- cycle type and exit signal
- output filenames and read/write flow
- any pattern-specific prompt boundaries or confirmation checks

### Generate execution_plan.json

Write the execution plan to `{run_dir}/execution_plan.json`:

```json
{
  "pattern": "{pattern-name}",
  "run_dir": "{absolute_path_to_run_dir}",
  "plugin_dir": "{absolute_path_to_plugin}",
  "nodes": [...],
  "cycles": [...],
  "final_output": "output/{final-output-filename}.md"
}
```

Node format:
```json
{
  "name": "{agent-name}",
  "agent_file": "{agent-name}.md",
  "depends_on": ["dep1", "dep2"],
  "parallel_group": "group-name-or-null",
  "outputs": ["output/filename.md"]
}
```

Cycle format (self-loop):
```json
{
  "type": "self-loop",
  "agent": "{agent-name}",
  "max_iterations": 3,
  "exit_signal_file": "output/constraint-met.flag"
}
```

Cycle format (bipartite):
```json
{
  "type": "bipartite",
  "producer": "{producer-name}",
  "evaluator": "{evaluator-name}",
  "max_rounds": 5,
  "exit_signal_file": "output/evaluation-pass.flag"
}
```

### Launch Orchestrator

After writing all files, launch the orchestrator as a background process:

```bash
python "{PLUGIN_ROOT}/scripts/orchestrator.py" --plan "{run_dir}/execution_plan.json" --geometry 900x700+4740+904
```

Use `run_in_background: true` with the Bash tool. Then tell the user:
- The orchestrator is running
- The graph monitor GUI should have opened
- The run directory path
- That you'll report the results when execution completes

Do not launch workflow agents with the `Agent` tool. The orchestrator must be the only component that invokes workflow agents, because it enforces per-agent CLI tool restrictions via `--tools` derived from each agent file's `tools` frontmatter.

Treat this skill's `allowed-tools` list as guidance, not as the security boundary for workflow agents. The hard enforcement point is the orchestrator's CLI invocation of each workflow agent with `--tools`.

### Monitor and Report

After launching, periodically check `{run_dir}/logs/status.json` to see if execution has completed. When the `state` field becomes `"completed"` or `"failed"`:

- Read the final output file (from `final_output` in the execution plan)
- Present a concise summary to the user
- If failed, read the errors and report what went wrong
- Tell the user the full output is in the run directory
- Ask if they want to keep the agent definitions (copy to `~/.claude/agents/`) or let them be cleaned up with the run
