---
description: "Run a multi-agent execution pattern on a task"
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash(*)
  - AskUserQuestion
  - Agent
---

You have been invoked to run a multi-agent execution pattern on a task of the user's choosing.

Activate the `multi-agent-graph-compose` skill now. Follow its instructions to guide the user through pattern selection, configuration, agent generation, and orchestration.

The plugin root is: `${CLAUDE_PLUGIN_ROOT}`

If the user provided a task description along with this command, pass it to the compose skill so it can skip the initial "what do you want accomplished?" question.
