# Project Registry

## Before anything else: run get-project-context.ps1

This project is tracked in the central registry. After structural changes:
- Update `D:\Dropbox\Projects\Management\projects.json` (architecture, workflow, version fields)
- Update `D:\Dropbox\Projects\multi-agent-graph.md` (Recent Changes, Directory Structure)

Triggers: new version folder, major dependency changes, build command changes.

# Versioning Convention

When editing a skill or agent in this plugin, always create a new versioned copy in the main repository folder before (or instead of) editing the deployed copy in-place.

- **Skills**: Version skills first under the central skills root `D:\Dropbox\Repository\LLMs\Claude\Skills\`. Copy to `D:\Dropbox\Repository\LLMs\Claude\Skills\multi-agent-graph-{skillname}\{skillname}_v{N+1}\` (with `references/` if present), then update the deployed copy in `skills/{skillname}/`.
- **Agents**: Copy to `D:\Dropbox\Repository\LLMs\Claude\Agents\multi-agent-graph-{agentname}\{agentname}_v{N+1}.md`, then update the deployed copy in `agents/`.

This ensures every iteration is preserved and recoverable. Never edit a deployed skill or agent without versioning first.

# Testing State

Active testing state is tracked in `TESTING-STATE.md` at the project root. **Read this file first** when resuming testing after context compaction. It contains: current test status for all 7 patterns, display/geometry config, hard constraints, background task status, and file locations.

**TESTING-STATE.md must never exceed 2500 tokens.** Re-tokenize after every update and prune as necessary. Standard command: `python D:\Dropbox\Repository\LLMs\temp\count_tokens.py D:\Dropbox\Repository\LLMs\Claude\Plugins\multi-agent-graph\TESTING-STATE.md`

# Run Directory Naming

All test/run outputs go in `runs/` with **YYMMDD_descriptive-task-name** folder names.
Example: `runs/260312_credit-card-transaction-lifecycle/`
