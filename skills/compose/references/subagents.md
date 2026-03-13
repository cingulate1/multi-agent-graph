# Subagents (Claude Code)

A subagent prompt is a system prompt for a subprocess spawned by a parent agent. The subagent operates with no conversation history, limited tools, and a narrow task scope.

## File Format

Subagent files are Markdown with YAML frontmatter. The frontmatter defines configuration; the body is the system prompt.

```markdown
---
name: my-subagent
description: When Claude should delegate to this subagent
tools: Read, Grep, Glob, Bash
model: sonnet
---

You are a specialist. When invoked, do the thing and return the result.
```

### Required Fields

| Field         | Description                                    |
|---------------|------------------------------------------------|
| `name`        | Unique identifier, lowercase letters and hyphens |
| `description` | Tells Claude when to delegate to this subagent |

### Optional Fields

| Field             | Description                                                         | Default       |
|-------------------|---------------------------------------------------------------------|---------------|
| `tools`           | Comma-separated tool names (allowlist)                              | Inherits all  |
| `disallowedTools` | Comma-separated tool names to deny (removed from inherited list)    | —             |
| `model`           | `sonnet`, `opus`, `haiku`, or `inherit`                             | `inherit`     |
| `permissionMode`  | `default`, `acceptEdits`, `dontAsk`, `bypassPermissions`, or `plan` | —             |
| `maxTurns`        | Max agentic turns before the subagent stops                         | —             |
| `skills`          | Skills to inject into the subagent's context at startup             | —             |
| `mcpServers`      | MCP servers available to this subagent                              | —             |
| `hooks`           | Lifecycle hooks scoped to this subagent                             | —             |
| `memory`          | Persistent memory scope: `user`, `project`, or `local`              | —             |
| `background`      | `true` to always run as a background task                           | `false`       |
| `isolation`       | `worktree` to run in a temporary git worktree                       | —             |

### File Locations

| Location             | Scope           | Priority    |
|----------------------|-----------------|-------------|
| `--agents` CLI flag  | Current session | 1 (highest) |
| `.claude/agents/`    | Current project | 2           |
| `~/.claude/agents/`  | All projects    | 3           |
| Plugin `agents/` dir | Plugin scope    | 4 (lowest)  |

## Key Constraints

- **No prior context** — The subagent doesn't see the parent's conversation. Everything it needs must be in the prompt or passed as parameters.
- **Limited tools** — Subagents typically have access to a subset of tools. Don't reference tools the subagent can't use.
- **Single task** — Subagents are spawned to do one thing and return a result. The prompt should reflect that focus.

## Structure

1. State the task — what the subagent should produce.
2. Provide the inputs — whatever context was extracted from the parent conversation that the subagent needs.
3. Specify constraints — output format, scope boundaries, what to do (and not do).

## What to Include

- The specific task and its success criteria.
- Domain context the subagent can't infer (schemas, conventions, terminology).
- The expected output format so the parent can parse the result.
- Scope boundaries — what's in and out of bounds for the subagent.

## What to Exclude

- Features, capabilities, or tools the subagent doesn't have access to.
- Background on why the parent is doing what it's doing, unless it affects the subagent's decisions.
- General instructions about being helpful or thorough. The model already does this.

## Common Mistakes

- **Copying the parent's full system prompt** — The subagent doesn't need the parent's persona, conversation rules, or tool descriptions for tools it can't use.
- **Omitting necessary context** — Assuming the subagent knows things from the parent conversation it was never told.
- **Vague return expectations** — If the parent needs to parse the result, the subagent needs to know what format to return.
