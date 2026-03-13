#!/usr/bin/env python3
"""Run the orchestrator against a test fixture and capture screenshots during execution.

Usage:
    python test_live_run.py chained-iteration
    python test_live_run.py consensus-panel
    python test_live_run.py all
"""

import json
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
RUNS_DIR = PLUGIN_ROOT / "runs"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

WINDOW_X = 4740
WINDOW_Y = 904
WINDOW_W = 900
WINDOW_H = 700
GEOMETRY = f"{WINDOW_W}x{WINDOW_H}+{WINDOW_X}+{WINDOW_Y}"

ALL_PATTERNS = [
    "chained-iteration",
    "rag-grounded-v2",
    "rubric-based-v2",
    "consensus-panel",
    "debate-panel",
    "dissensus-integration",
    "parallel-decomposition",
]


def screenshot(save_path: Path) -> bool:
    ps_cmd = (
        'Add-Type -AssemblyName System.Drawing; '
        f'$bmp = New-Object System.Drawing.Bitmap({WINDOW_W}, {WINDOW_H}); '
        '$g = [System.Drawing.Graphics]::FromImage($bmp); '
        f'$g.CopyFromScreen({WINDOW_X}, {WINDOW_Y}, 0, 0, $bmp.Size); '
        '$g.Dispose(); '
        f'$bmp.Save("{save_path}", [System.Drawing.Imaging.ImageFormat]::Png); '
        '$bmp.Dispose()'
    )
    result = subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and save_path.exists()


def reset_run_dir(run_dir: Path) -> None:
    """Clean status and output so the orchestrator starts fresh."""
    status_path = run_dir / "logs" / "status.json"
    if status_path.exists():
        status_path.unlink()
    # Clean output files/directories (orchestrator expects to create them)
    output_dir = run_dir / "output"
    if output_dir.exists():
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    # Clean exit signal files
    for flag in run_dir.glob("output/*.flag"):
        flag.unlink()
    signal = run_dir / "_final_round"
    if signal.exists():
        signal.unlink()


def read_status(run_dir: Path) -> dict | None:
    status_path = run_dir / "logs" / "status.json"
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_run_dir(run_dir: Path, pattern_label: str | None = None) -> list[Path]:
    """Run orchestrator for a specific run directory and capture screenshots."""
    run_dir = Path(run_dir).resolve()
    if not run_dir.exists():
        print(f"  [ERROR] Run directory does not exist: {run_dir}")
        return []

    plan_path = run_dir / "execution_plan.json"
    if not plan_path.exists():
        print(f"  [ERROR] Missing execution plan: {plan_path}")
        return []

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        plan = {}
    pattern = pattern_label or plan.get("pattern") or run_dir.name

    screenshot_dir = run_dir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    # Clean old screenshots
    for f in screenshot_dir.glob("*.png"):
        f.unlink()

    # Reset run state
    reset_run_dir(run_dir)

    print(f"\n  === {pattern} ===")
    print(f"  Run dir: {run_dir}")
    print(f"  GUI geometry: {GEOMETRY}")

    # Start orchestrator with GUI at fixed position
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "orchestrator.py"),
        "--plan", str(plan_path),
        "--geometry", GEOMETRY,
    ]
    print(f"  Starting orchestrator...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(SCRIPTS_DIR),
    )

    screenshots = []
    shot_num = 0
    last_state_hash = None

    # Wait for GUI to initialize
    time.sleep(3.0)

    # Take initial screenshot
    path = screenshot_dir / f"phase_{shot_num:02d}_init.png"
    if screenshot(path):
        screenshots.append(path)
        print(f"  [SHOT] {path.name}")
    shot_num += 1

    # Poll status.json and take screenshots on state changes
    max_wait = 1800  # 30 minutes max (panel patterns with Opus agents take time)
    start = time.time()
    while proc.poll() is None and (time.time() - start) < max_wait:
        time.sleep(3.0)

        status = read_status(run_dir)
        if status:
            # Build a hash of node states to detect changes
            node_states = {k: v["state"] for k, v in status.get("nodes", {}).items()}
            cycle_states = {k: (v["state"], v.get("current_round")) for k, v in status.get("cycles", {}).items()}
            state_hash = (status.get("state"), str(node_states), str(cycle_states))

            if state_hash != last_state_hash:
                last_state_hash = state_hash
                activity = status.get("activity", "")
                overall = status.get("state", "?")
                label = f"phase_{shot_num:02d}_{overall}"
                path = screenshot_dir / f"{label}.png"
                if screenshot(path):
                    screenshots.append(path)
                    print(f"  [SHOT] {path.name} — {activity}")
                shot_num += 1

        if status and status.get("state") in ("completed", "failed"):
            # One more screenshot after a brief settle
            time.sleep(1.5)
            path = screenshot_dir / f"phase_{shot_num:02d}_final.png"
            if screenshot(path):
                screenshots.append(path)
                print(f"  [SHOT] {path.name} — FINAL")
            break

    # Wait for orchestrator to finish
    try:
        stdout, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()

    rc = proc.returncode
    if rc == 0:
        print(f"  [OK] Orchestrator exited successfully")
    else:
        print(f"  [FAIL] Orchestrator exited with code {rc}")
        if stdout:
            # Print last 20 lines of output
            lines = stdout.strip().split('\n')
            for line in lines[-20:]:
                print(f"    {line}")

    print(f"  Screenshots: {len(screenshots)}")
    return screenshots


def run_pattern(pattern: str) -> list[Path]:
    """Run orchestrator for a test-harness pattern fixture and capture screenshots."""
    run_dir = RUNS_DIR / f"test_{pattern}"
    if not run_dir.exists():
        print(f"  [ERROR] No fixture for {pattern}. Run test_harness.py first.")
        return []
    return run_run_dir(run_dir, pattern_label=pattern)


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_live_run.py <pattern|all>")
        sys.exit(1)

    target = sys.argv[1]
    patterns = ALL_PATTERNS if target == "all" else [target]

    print("=" * 60)
    print("multi-agent-graph — Live Orchestrator Test")
    print("=" * 60)
    print(f"DO NOT move or obscure the GUI window during capture.")

    all_shots = {}
    for pattern in patterns:
        shots = run_pattern(pattern)
        all_shots[pattern] = shots

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for pattern, shots in all_shots.items():
        status = "OK" if shots else "NO SCREENSHOTS"
        print(f"  {pattern}: {len(shots)} screenshots [{status}]")
        for s in shots:
            print(f"    {s}")


if __name__ == "__main__":
    main()
