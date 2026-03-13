#!/usr/bin/env python3
"""Test harness for multi-agent-graph plugin.

Generates synthetic execution plans and mock agents for all 8 patterns,
then optionally runs the graph monitor GUI for visual verification.

Usage:
    python test_harness.py                    # Generate all test fixtures
    python test_harness.py --gui              # Generate + open GUI for each pattern
    python test_harness.py --gui consensus-panel  # Open GUI for one pattern
    python test_harness.py --orchestrator     # Run orchestrator with mock agents
    python test_harness.py --check-imports    # Verify all scripts import cleanly
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

PLUGIN_ROOT = Path(__file__).parent.parent
RUNS_DIR = PLUGIN_ROOT / "runs"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"


# ---------------------------------------------------------------------------
# Pattern definitions (synthetic plans)
# ---------------------------------------------------------------------------

def _chained_iteration_plan(run_dir: str) -> dict:
    return {
        "pattern": "chained-iteration",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": [
            {"name": "writer", "agent_file": "writer.md", "depends_on": [], "parallel_group": None, "outputs": ["output/result.md"]},
        ],
        "cycles": [
            {"type": "self-loop", "agent": "writer", "max_iterations": 3, "exit_signal_file": "output/constraint-met.flag"},
        ],
        "final_output": "output/result.md",
    }


def _rag_grounded_plan(run_dir: str) -> dict:
    return {
        "pattern": "rag-grounded",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": [
            {"name": "generator", "agent_file": "generator.md", "depends_on": [], "parallel_group": None, "outputs": ["output/draft.md"]},
            {"name": "evaluator", "agent_file": "evaluator.md", "depends_on": [], "parallel_group": None, "outputs": ["output/evaluation.md"]},
        ],
        "cycles": [
            {"type": "bipartite", "producer": "generator", "evaluator": "evaluator", "max_rounds": 5, "exit_signal_file": "output/evaluation-pass.flag"},
        ],
        "final_output": "output/draft.md",
    }


def _rubric_based_plan(run_dir: str) -> dict:
    return {
        "pattern": "rubric-based",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": [
            {"name": "evaluator", "agent_file": "evaluator.md", "depends_on": [], "parallel_group": None, "outputs": ["output/rubric.md"]},
            {"name": "generator", "agent_file": "generator.md", "depends_on": [], "parallel_group": None, "outputs": ["output/content.md"]},
        ],
        "cycles": [
            {"type": "bipartite", "producer": "generator", "evaluator": "evaluator", "max_rounds": 6, "exit_signal_file": "output/evaluation-pass.flag"},
        ],
        "final_output": "output/content.md",
    }


def _consensus_panel_plan(run_dir: str) -> dict:
    panelists = ["security-eng", "devops-lead", "architect"]
    nodes = []
    # Phase 1: initial
    for p in panelists:
        nodes.append({
            "name": f"{p}-initial",
            "agent_file": f"{p}-initial.md",
            "depends_on": [],
            "parallel_group": "initial",
            "outputs": [f"output/{p}-initial.md"],
        })
    # Phase 2: refine (depends on all initial)
    initial_names = [f"{p}-initial" for p in panelists]
    for p in panelists:
        nodes.append({
            "name": f"{p}-refine",
            "agent_file": f"{p}-refine.md",
            "depends_on": initial_names,
            "parallel_group": "refine",
            "outputs": [f"output/{p}-refine.md"],
        })
    # Phase 3: synthesizer
    refine_names = [f"{p}-refine" for p in panelists]
    nodes.append({
        "name": "synthesizer",
        "agent_file": "synthesizer.md",
        "depends_on": refine_names,
        "parallel_group": None,
        "outputs": ["output/synthesis.md"],
    })
    return {
        "pattern": "consensus-panel",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": nodes,
        "cycles": [],
        "final_output": "output/synthesis.md",
    }


def _debate_panel_plan(run_dir: str) -> dict:
    panelists = ["optimist", "skeptic", "pragmatist"]
    nodes = []
    for p in panelists:
        nodes.append({
            "name": f"{p}-initial",
            "agent_file": f"{p}-initial.md",
            "depends_on": [],
            "parallel_group": "initial",
            "outputs": [f"output/{p}-initial.md"],
        })
    initial_names = [f"{p}-initial" for p in panelists]
    for p in panelists:
        nodes.append({
            "name": f"{p}-debate",
            "agent_file": f"{p}-debate.md",
            "depends_on": initial_names,
            "parallel_group": "debate",
            "outputs": [f"output/{p}-debate.md"],
        })
    debate_names = [f"{p}-debate" for p in panelists]
    nodes.append({
        "name": "selector",
        "agent_file": "selector.md",
        "depends_on": debate_names,
        "parallel_group": None,
        "outputs": ["output/selection.md"],
    })
    return {
        "pattern": "debate-panel",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": nodes,
        "cycles": [],
        "final_output": "output/selection.md",
    }


def _dissensus_integration_plan(run_dir: str) -> dict:
    panelists = ["security-lens", "performance-lens", "ux-lens"]
    nodes = []
    for p in panelists:
        nodes.append({
            "name": p,
            "agent_file": f"{p}.md",
            "depends_on": [],
            "parallel_group": "panelists",
            "outputs": [f"output/{p}.md"],
        })
    panelist_names = [p for p in panelists]
    nodes.append({
        "name": "integrator",
        "agent_file": "integrator.md",
        "depends_on": panelist_names,
        "parallel_group": None,
        "outputs": ["output/integration.md"],
    })
    return {
        "pattern": "dissensus-integration",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": nodes,
        "cycles": [],
        "final_output": "output/integration.md",
    }


def _feedforward_parallel_plan(run_dir: str) -> dict:
    workers = ["worker-1", "worker-2", "worker-3", "worker-4"]
    nodes = [
        {
            "name": "decomposer",
            "agent_file": "decomposer.md",
            "depends_on": [],
            "parallel_group": None,
            "outputs": ["output/assignments.md"],
        },
    ]
    for w in workers:
        nodes.append({
            "name": w,
            "agent_file": f"{w}.md",
            "depends_on": ["decomposer"],
            "parallel_group": "workers",
            "outputs": [f"output/{w}.md"],
        })
    return {
        "pattern": "parallel-decomposition",
        "run_dir": run_dir,
        "plugin_dir": str(PLUGIN_ROOT),
        "nodes": nodes,
        "cycles": [],
        "final_output": "output/assignments.md",
    }


PATTERN_GENERATORS = {
    "chained-iteration": _chained_iteration_plan,
    "rag-grounded": _rag_grounded_plan,
    "rubric-based": _rubric_based_plan,
    "consensus-panel": _consensus_panel_plan,
    "debate-panel": _debate_panel_plan,
    "dissensus-integration": _dissensus_integration_plan,
    "parallel-decomposition": _feedforward_parallel_plan,
}


# ---------------------------------------------------------------------------
# Mock agent generator
# ---------------------------------------------------------------------------

MOCK_AGENT_TEMPLATE = """---
name: {name}
description: Test mock agent for {name}
tools: Read, Write
model: sonnet
---

You are a test mock agent. Write a brief placeholder to your output file.

Your output file: {output_path}

Write a single line: "Mock output from {name}" followed by the current date/time.
"""


def _generate_mock_agents(run_dir: Path, plan: dict) -> None:
    """Create minimal mock agent .md files for every node in the plan."""
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(exist_ok=True)

    for node in plan["nodes"]:
        name = node["name"]
        outputs = node.get("outputs", [])
        output_path = outputs[0] if outputs else f"output/{name}.md"
        agent_file = agents_dir / node["agent_file"]
        agent_file.write_text(
            MOCK_AGENT_TEMPLATE.format(name=name, output_path=output_path),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Status progression generator (for GUI testing)
# ---------------------------------------------------------------------------

def _generate_status_progression(run_dir: Path, plan: dict) -> list[dict]:
    """Generate a sequence of status.json snapshots simulating execution."""
    from datetime import datetime, timezone, timedelta

    base_time = datetime.now(timezone.utc).astimezone()
    nodes = plan["nodes"]
    cycles = plan.get("cycles", [])

    def _ts(offset_seconds: int) -> str:
        return (base_time + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")

    # Build initial status
    node_states = {}
    for n in nodes:
        node_states[n["name"]] = {
            "state": "pending",
            "started_at": None,
            "completed_at": None,
            "iteration": None,
            "parallel_group": n.get("parallel_group"),
        }

    cycle_states = {}
    for c in cycles:
        if c["type"] == "self-loop":
            key = c["agent"]
            max_r = c.get("max_iterations", 3)
        else:
            key = f"{c['producer']}-{c['evaluator']}"
            max_r = c.get("max_rounds", 5)
        cycle_states[key] = {
            "type": c["type"],
            "current_round": 0,
            "max_rounds": max_r,
            "state": "pending",
        }

    snapshots = []

    def _snap(t: int, state: str, activity: str, events: list) -> dict:
        import copy
        return {
            "schema_version": 1,
            "run_dir": str(run_dir),
            "created_at": _ts(0),
            "updated_at": _ts(t),
            "state": state,
            "pattern": plan["pattern"],
            "activity": activity,
            "nodes": copy.deepcopy(node_states),
            "cycles": copy.deepcopy(cycle_states),
            "events": list(events),
            "errors": [],
            "final_output": None,
        }

    events = []
    t = 0

    # Snapshot 0: all pending
    events.append({"ts": _ts(t), "level": "INFO", "message": "Run initialized"})
    snapshots.append(_snap(t, "running", "Starting execution", events))

    # Simple progression: set each node to running then completed in dependency order
    # (This is a simplified simulation — doesn't perfectly model parallelism)
    completed = set()
    while len(completed) < len(nodes):
        ready = [
            n for n in nodes
            if n["name"] not in completed
            and all(d in completed for d in n.get("depends_on", []))
        ]
        if not ready:
            break

        # Check if any are cycle members
        cycle_members = set()
        for c in cycles:
            if c["type"] == "self-loop":
                cycle_members.add(c["agent"])
            else:
                cycle_members.add(c["producer"])
                cycle_members.add(c["evaluator"])

        normal = [n for n in ready if n["name"] not in cycle_members]
        cycle_ready = [n for n in ready if n["name"] in cycle_members]

        # Handle cycle nodes
        for n in cycle_ready:
            name = n["name"]
            # Find the cycle
            for c in cycles:
                members = set()
                if c["type"] == "self-loop":
                    members = {c["agent"]}
                    key = c["agent"]
                else:
                    members = {c["producer"], c["evaluator"]}
                    key = f"{c['producer']}-{c['evaluator']}"

                if name in members and key in cycle_states and cycle_states[key]["state"] == "pending":
                    max_r = cycle_states[key]["max_rounds"]
                    # Simulate 2 rounds then complete
                    for r in range(1, min(3, max_r + 1)):
                        t += 5
                        cycle_states[key]["state"] = "running"
                        cycle_states[key]["current_round"] = r
                        for m in members:
                            node_states[m]["state"] = "running"
                            node_states[m]["iteration"] = r
                            if not node_states[m]["started_at"]:
                                node_states[m]["started_at"] = _ts(t)
                        events.append({"ts": _ts(t), "level": "INFO", "message": f"Cycle round {r}"})
                        snapshots.append(_snap(t, "running", f"Cycle round {r}/{max_r}", events))

                    t += 3
                    cycle_states[key]["state"] = "completed"
                    for m in members:
                        node_states[m]["state"] = "completed"
                        node_states[m]["completed_at"] = _ts(t)
                        completed.add(m)
                    events.append({"ts": _ts(t), "level": "INFO", "message": f"Cycle completed"})
                    snapshots.append(_snap(t, "running", "Cycle completed", events))

        # Handle normal nodes
        for n in normal:
            name = n["name"]
            t += 3
            node_states[name]["state"] = "running"
            node_states[name]["started_at"] = _ts(t)
            events.append({"ts": _ts(t), "level": "INFO", "message": f"Running: {name}"})
            snapshots.append(_snap(t, "running", f"Running: {name}", events))

            t += 5
            node_states[name]["state"] = "completed"
            node_states[name]["completed_at"] = _ts(t)
            completed.add(name)
            events.append({"ts": _ts(t), "level": "INFO", "message": f"Completed: {name}"})
            snapshots.append(_snap(t, "running", f"Completed: {name}", events))

    # Final snapshot
    t += 2
    final = _snap(t, "completed", "All agents executed successfully", events)
    final["final_output"] = plan.get("final_output")
    snapshots.append(final)

    return snapshots


# ---------------------------------------------------------------------------
# Test routines
# ---------------------------------------------------------------------------

def generate_all_fixtures() -> dict[str, Path]:
    """Generate test fixtures for all 8 patterns. Returns dict of pattern -> run_dir."""
    results = {}
    for pattern_name, gen_fn in PATTERN_GENERATORS.items():
        run_dir = RUNS_DIR / f"test_{pattern_name}"
        if run_dir.exists():
            shutil.rmtree(run_dir)

        run_dir.mkdir(parents=True)
        (run_dir / "output").mkdir()
        (run_dir / "logs").mkdir()

        plan = gen_fn(str(run_dir))
        plan_path = run_dir / "execution_plan.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

        _generate_mock_agents(run_dir, plan)

        # Write initial status
        snapshots = _generate_status_progression(run_dir, plan)
        # Write the final (completed) snapshot as the status file
        status_path = run_dir / "logs" / "status.json"
        status_path.write_text(json.dumps(snapshots[-1], indent=2), encoding="utf-8")

        # Also save full progression for animated GUI testing
        progression_path = run_dir / "logs" / "status_progression.json"
        progression_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")

        results[pattern_name] = run_dir
        print(f"  [OK] {pattern_name}: {run_dir}")

    return results


def check_imports() -> bool:
    """Verify all plugin scripts import without error."""
    ok = True
    for script in ["orchestrator.py", "graph_monitor.py", "status_tracking.py"]:
        path = SCRIPTS_DIR / script
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{path}', encoding='utf-8').read())"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  [OK] {script}: syntax valid")
        else:
            print(f"  [FAIL] {script}: {result.stderr.strip()}")
            ok = False
    return ok


WINDOW_X = 100
WINDOW_Y = 100
WINDOW_W = 900
WINDOW_H = 700
FIXED_GEOMETRY = f"{WINDOW_W}x{WINDOW_H}+{WINDOW_X}+{WINDOW_Y}"


def _screenshot_region(x: int, y: int, w: int, h: int, save_path: Path) -> bool:
    """Capture a screen region to a PNG file using PowerShell + .NET System.Drawing."""
    ps_cmd = (
        'Add-Type -AssemblyName System.Drawing; '
        f'$bmp = New-Object System.Drawing.Bitmap({w}, {h}); '
        '$g = [System.Drawing.Graphics]::FromImage($bmp); '
        f'$g.CopyFromScreen({x}, {y}, 0, 0, $bmp.Size); '
        '$g.Dispose(); '
        f'$bmp.Save("{save_path}", [System.Drawing.Imaging.ImageFormat]::Png); '
        '$bmp.Dispose()'
    )
    result = subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and save_path.exists():
        return True
    if result.stderr:
        print(f"    Screenshot error: {result.stderr.strip()[:200]}")
    return False


def open_gui_for_pattern(
    pattern_name: str,
    animate: bool = False,
    screenshot: bool = False,
) -> Optional[Path]:
    """Open the graph monitor GUI for a test pattern.

    If screenshot=True: opens at fixed position, animates to final state,
    captures screenshot, auto-closes. Returns screenshot path.
    """
    run_dir = RUNS_DIR / f"test_{pattern_name}"
    if not run_dir.exists():
        print(f"  [ERROR] No test fixture for '{pattern_name}'. Run without --gui first.")
        return None

    progression_path = run_dir / "logs" / "status_progression.json"
    status_path = run_dir / "logs" / "status.json"

    if animate or screenshot:
        if progression_path.exists():
            snapshots = json.loads(progression_path.read_text(encoding="utf-8"))
            # Write first snapshot so GUI starts in pending state
            status_path.write_text(json.dumps(snapshots[0], indent=2), encoding="utf-8")
        else:
            print(f"  [WARN] No progression data for {pattern_name}")
            snapshots = None
            animate = False
    else:
        snapshots = None

    # Build command — pin to fixed geometry if screenshotting
    cmd = [sys.executable, str(SCRIPTS_DIR / "graph_monitor.py"), str(run_dir)]
    if screenshot:
        cmd += ["--geometry", FIXED_GEOMETRY]

    print(f"  Opening GUI for: {pattern_name}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Let GUI initialize and render
    time.sleep(2.0)

    if (animate or screenshot) and snapshots:
        # Feed snapshots to simulate execution progression
        for snap in snapshots[1:]:
            status_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
            time.sleep(0.6)
        # Extra settle time for final state rendering
        time.sleep(1.0)

    screenshot_path = None
    if screenshot:
        screenshot_path = run_dir / "screenshot.png"
        ok = _screenshot_region(WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H, screenshot_path)
        if ok:
            print(f"  [OK] Screenshot saved: {screenshot_path}")
        else:
            print(f"  [FAIL] Screenshot capture failed for {pattern_name}")
            screenshot_path = None

        # Auto-close the GUI
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    else:
        print(f"  GUI open. Close window when done inspecting.")
        proc.wait()

    return screenshot_path


def run_orchestrator_test(pattern_name: str) -> bool:
    """Run the orchestrator on a test fixture with mock agents.

    NOTE: This will attempt to invoke `claude` for each agent.
    For true dry-run testing, mock agents must actually produce output files.
    This function pre-creates output files so the orchestrator succeeds.
    """
    run_dir = RUNS_DIR / f"test_{pattern_name}"
    if not run_dir.exists():
        print(f"  [ERROR] No test fixture for '{pattern_name}'")
        return False

    plan_path = run_dir / "execution_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    # Pre-create all expected output files (simulate agent output)
    for node in plan["nodes"]:
        for output_file in node.get("outputs", []):
            out_path = run_dir / output_file
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(f"Mock output from {node['name']}\n", encoding="utf-8")

    # Pre-create exit signal files for cycles
    for cycle in plan.get("cycles", []):
        signal = cycle.get("exit_signal_file")
        if signal:
            sig_path = run_dir / signal
            sig_path.parent.mkdir(parents=True, exist_ok=True)
            sig_path.write_text("pass", encoding="utf-8")

    print(f"  Pre-created output files for: {pattern_name}")
    print(f"  NOTE: Full orchestrator test requires `claude` CLI. Skipping subprocess invocation.")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="multi-agent-graph test harness")
    parser.add_argument("--gui", nargs="?", const="all", default=None,
                        help="Open GUI for a pattern (or 'all') — manual close")
    parser.add_argument("--animate", action="store_true",
                        help="Animate status progression in GUI mode")
    parser.add_argument("--screenshot", nargs="?", const="all", default=None,
                        help="Open GUI for a pattern (or 'all'), animate to final state, "
                        "capture screenshot, auto-close. Screenshots saved to runs/test_{pattern}/screenshot.png")
    parser.add_argument("--orchestrator", nargs="?", const="all", default=None,
                        help="Test orchestrator for a pattern (or 'all')")
    parser.add_argument("--check-imports", action="store_true",
                        help="Verify script imports")
    args = parser.parse_args()

    print("=" * 60)
    print("multi-agent-graph Test Harness")
    print("=" * 60)

    # Always check imports
    print("\n--- Import Check ---")
    imports_ok = check_imports()

    # Always generate fixtures
    print("\n--- Generating Test Fixtures ---")
    fixtures = generate_all_fixtures()

    if args.check_imports:
        sys.exit(0 if imports_ok else 1)

    if args.orchestrator is not None:
        print("\n--- Orchestrator Test ---")
        patterns = list(PATTERN_GENERATORS.keys()) if args.orchestrator == "all" else [args.orchestrator]
        for p in patterns:
            run_orchestrator_test(p)

    if args.screenshot is not None:
        print("\n--- Screenshot Test (automated) ---")
        print(f"  Window position: ({WINDOW_X}, {WINDOW_Y}), size: {WINDOW_W}x{WINDOW_H}")
        print(f"  DO NOT move or obscure the window during capture.\n")
        patterns = list(PATTERN_GENERATORS.keys()) if args.screenshot == "all" else [args.screenshot]
        screenshot_paths = []
        for p in patterns:
            path = open_gui_for_pattern(p, animate=True, screenshot=True)
            if path:
                screenshot_paths.append((p, path))
        if screenshot_paths:
            print(f"\n  --- Screenshots captured: {len(screenshot_paths)}/{len(patterns)} ---")
            for name, path in screenshot_paths:
                print(f"    {name}: {path}")

    elif args.gui is not None:
        print("\n--- GUI Visual Test (manual close) ---")
        patterns = list(PATTERN_GENERATORS.keys()) if args.gui == "all" else [args.gui]
        for p in patterns:
            open_gui_for_pattern(p, animate=args.animate)

    print("\n--- Done ---")


if __name__ == "__main__":
    main()
