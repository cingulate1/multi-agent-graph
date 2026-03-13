# How to Run a Compose Test (Manual Harness)

## What This Is

The multi-agent-graph plugin has a "compose" skill that guides a Socratic exchange to configure and launch multi-agent workflows. Testing it means playing the role of a user talking to compose, one turn at a time, via `claude -p` subprocess calls.

## The Conversation Loop

### Turn 1 (new session)

```bash
unset CLAUDECODE && claude -p "YOUR OPENING MESSAGE" \
  --plugin-dir "D:\Dropbox\Repository\LLMs\Claude\Plugins\multi-agent-graph" \
  --model sonnet \
  --output-format stream-json \
  --verbose \
  --dangerously-skip-permissions \
  --session-id "SESSION_UUID"
```

Generate `SESSION_UUID` beforehand: `python -c "import uuid; print(uuid.uuid4())"`

### Turn 2+ (resume)

```bash
unset CLAUDECODE && claude -p "YOUR REPLY" \
  --plugin-dir "D:\Dropbox\Repository\LLMs\Claude\Plugins\multi-agent-graph" \
  --model sonnet \
  --output-format stream-json \
  --verbose \
  --dangerously-skip-permissions \
  --resume "SESSION_UUID"
```

The only difference is `--resume SESSION_UUID` replaces `--session-id SESSION_UUID`.

### Environment Notes

- `unset CLAUDECODE` is required — without it, the subprocess detects it's inside another Claude session and refuses to start.
- The test harness script (`test_e2e.py`) also strips `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the env to avoid accidental API billing. When running manually via Bash tool, `unset CLAUDECODE` is sufficient (the subscription handles auth).

## Reading the Output

The output is `stream-json` — one JSON object per line. To extract what compose said:

1. **Save raw output** to a temp file (pipe stdout to file, or capture in variable).
2. **Extract the final text**: Look for the last event with `"type": "result"` — its `"result"` field is compose's response text.
3. **Fallback**: If no `result` event, collect all `"type": "assistant"` events, then from each event's `message.content` array, collect items with `"type": "text"` and concatenate their `"text"` fields.
4. **Check for tool uses**: In `"type": "assistant"` events, look for `message.content` items with `"type": "tool_use"` — if compose called `Bash` with a command containing `orchestrator.py`, it launched the orchestrator and the workflow is running.
5. **Session ID confirmation**: Any event may contain a `"session_id"` field — use this to confirm the session ID for subsequent turns.

### Practical shortcut

Pipe to a temp file, then use a Python one-liner to extract compose's reply:

```bash
# After saving raw output to /tmp/compose_turn_N.json:
python -c "
import json, sys
events = [json.loads(l) for l in open(sys.argv[1]) if l.strip().startswith('{')]
for e in reversed(events):
    if e.get('type') == 'result' and e.get('result', '').strip():
        print(e['result']); break
" /tmp/compose_turn_N.json
```

## Conversation Strategy

- **Turn 1**: State the task naturally. Don't over-specify — let compose ask questions per its Socratic exchange flow.
- **Subsequent turns**: Answer compose's questions. Confirm or adjust its recommendations.
- **Final turn**: Compose writes agent files, execution plan, and launches the orchestrator. Watch for a Bash tool use containing `orchestrator.py`.

## After Orchestrator Launch

Once compose launches the orchestrator, the workflow runs as a background process. Monitor via:

- `runs/<run-name>/logs/status.json` — node states, cycle rounds
- `runs/<run-name>/logs/*.log` — per-agent logs
- `runs/<run-name>/output/` — artifacts produced by agents

The test_live_run.py script can also run against a populated run directory to capture GUI screenshots:

```bash
python scripts/test_live_run.py parallel-decomposition
```

Or run directly against any run directory:

```python
from test_live_run import run_run_dir
run_run_dir("D:/Dropbox/.../runs/260313_some-run")
```

## Current Test: Parallel Decomposition

- **Corpus**: `D:\Dropbox\Repository\LLMs\temp\papers-to-summarize` (pre-populated with markdown research papers)
- **Opening message**: Keep it simple — mention the paper folder and that you want parallel decomposition. Let compose figure out the details.
- **Expected topology**: Decomposer (Opus) → dynamic fan-out of Haiku workers, one per paper
- **No cycles**: Pure fan-out, no bipartite refinement loops
- **Key test**: Dynamic worker template materialization — decomposer inspects corpus and writes manifest, orchestrator spawns workers from template
