#!/usr/bin/env python3
"""Invoke Haiku agents to evaluate pairwise semantic similarity for debate-panel scoring.

For each round transition, for each panelist, asks two questions:
  Q1: To what extent did this panelist change their answer? (1-5)
  Q2: To what extent did each other panelist move toward this panelist's answer? (1-5)

Each evaluation is an independent Haiku invocation with no knowledge of the
larger workflow. Samples cycle through three prompt variants to decorrelate
repeated evaluations:
  Variant 0: Standard 1-5 numeric scale, Respondent A/B labels
  Variant 1: A-E letter scale, Respondent 1/2 labels
  Variant 2: Reversed 5-1 numeric scale, Respondent A/B labels
All responses are normalized back to canonical 1-5 before writing.

Writes one CSV file per evaluation to output/evaluations/eval-NNNN.csv,
each containing a single integer 1-5.

Usage:
    cd <run_dir> && python run_semantic_evals.py
    cd <run_dir> && python run_semantic_evals.py --samples 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROUND_FILE_PATTERN = re.compile(r"^(.+)-round(\d+)\.md$")
HAIKU_TIMEOUT = 120  # 2 minutes per evaluation — these are tiny

log = logging.getLogger("run_semantic_evals")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def _agent_env():
    """Return an environment dict safe for spawning nested claude processes."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_panelists(output_dir: Path) -> tuple[list[str], int]:
    """Discover panelist names and round count from output files."""
    roster: dict[str, set[int]] = defaultdict(set)
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_file():
            continue
        match = ROUND_FILE_PATTERN.match(entry.name)
        if not match:
            continue
        roster[match.group(1)].add(int(match.group(2)))

    if not roster:
        raise RuntimeError("No panelist round files found")

    panelists = sorted(roster.keys())
    num_rounds = max(r for rounds in roster.values() for r in rounds) + 1
    return panelists, num_rounds


def read_final_answer(file_path: Path) -> str:
    """Read a panelist output file and extract the ## Final Answer section."""
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    heading_re = re.compile(r"^##\s+Final\s+Answer\s*$", re.IGNORECASE)

    heading_idx = None
    for i, line in enumerate(lines):
        if heading_re.match(line.strip()):
            heading_idx = i

    if heading_idx is not None:
        return "\n".join(lines[heading_idx + 1:]).strip()
    # Fall back to full content if no heading found
    return content.strip()


# ---------------------------------------------------------------------------
# Task ID generation
# ---------------------------------------------------------------------------

def task_id_for(eval_index: int) -> str:
    """Generate a deterministic task ID from the 4-digit evaluation index."""
    padded = f"{eval_index:04d}"
    return hashlib.sha256(padded.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _prompt_variant(sample: int) -> int:
    """Return the prompt variant (0, 1, or 2) for a given sample index."""
    return sample % 3


def build_q1_prompt(
    task_id: str,
    panelist: str,
    answer_before: str,
    answer_after: str,
    variant: int = 0,
) -> str:
    """Build the Q1 prompt: how much did this panelist change their answer?"""
    if variant == 1:
        scale = (
            "A = No change at all — the same recommendation/conclusion, possibly reworded\n"
            "B = Minor refinement — same core position with small additions or clarifications\n"
            "C = Moderate shift — the core recommendation is recognizably similar but with significant modifications\n"
            "D = Major change — the conclusion has substantially shifted, though some elements remain\n"
            "E = Complete reversal — an entirely different position\n\n"
            "Respond with a single letter from A to E. Nothing else."
        )
    elif variant == 2:
        scale = (
            "5 = No change at all — the same recommendation/conclusion, possibly reworded\n"
            "4 = Minor refinement — same core position with small additions or clarifications\n"
            "3 = Moderate shift — the core recommendation is recognizably similar but with significant modifications\n"
            "2 = Major change — the conclusion has substantially shifted, though some elements remain\n"
            "1 = Complete reversal — an entirely different position\n\n"
            "Respond with a single integer from 1 to 5. Nothing else."
        )
    else:
        scale = (
            "1 = No change at all — the same recommendation/conclusion, possibly reworded\n"
            "2 = Minor refinement — same core position with small additions or clarifications\n"
            "3 = Moderate shift — the core recommendation is recognizably similar but with significant modifications\n"
            "4 = Major change — the conclusion has substantially shifted, though some elements remain\n"
            "5 = Complete reversal — an entirely different position\n\n"
            "Respond with a single integer from 1 to 5. Nothing else."
        )

    return f"""<taskID>{task_id}</taskID>

You are evaluating how much a respondent changed their position between two rounds of a discussion.

Here is the respondent's answer in the earlier round:

<answer_before>
{answer_before}
</answer_before>

Here is the respondent's answer in the later round:

<answer_after>
{answer_after}
</answer_after>

To what extent did the respondent change their core position?

{scale}"""


def build_q2_prompt(
    task_id: str,
    panelist: str,
    other: str,
    other_answer_before: str,
    other_answer_after: str,
    panelist_answer: str,
    variant: int = 0,
) -> str:
    """Build a Q2 prompt: how much did the other panelist move toward this panelist?"""
    if variant == 1:
        ref_label, other_label = "Respondent 1", "Respondent 2"
        ref_tag, other_before_tag, other_after_tag = "respondent_1", "respondent_2_before", "respondent_2_after"
        scale = (
            "A = No movement toward 1 — 2's position is equally or more distant from 1\n"
            "B = Slight movement — 2 adopted minor elements of 1's position\n"
            "C = Moderate convergence — 2's new position shares significant common ground with 1\n"
            "D = Strong convergence — 2's new position is closely aligned with 1\n"
            "E = Full adoption — 2 essentially adopted 1's position\n\n"
            "Respond with a single letter from A to E. Nothing else."
        )
    elif variant == 2:
        ref_label, other_label = "Respondent A", "Respondent B"
        ref_tag, other_before_tag, other_after_tag = "respondent_a", "respondent_b_before", "respondent_b_after"
        scale = (
            "5 = No movement toward A — B's position is equally or more distant from A\n"
            "4 = Slight movement — B adopted minor elements of A's position\n"
            "3 = Moderate convergence — B's new position shares significant common ground with A\n"
            "2 = Strong convergence — B's new position is closely aligned with A\n"
            "1 = Full adoption — B essentially adopted A's position\n\n"
            "Respond with a single integer from 1 to 5. Nothing else."
        )
    else:
        ref_label, other_label = "Respondent A", "Respondent B"
        ref_tag, other_before_tag, other_after_tag = "respondent_a", "respondent_b_before", "respondent_b_after"
        scale = (
            "1 = No movement toward A — B's position is equally or more distant from A\n"
            "2 = Slight movement — B adopted minor elements of A's position\n"
            "3 = Moderate convergence — B's new position shares significant common ground with A\n"
            "4 = Strong convergence — B's new position is closely aligned with A\n"
            "5 = Full adoption — B essentially adopted A's position\n\n"
            "Respond with a single integer from 1 to 5. Nothing else."
        )

    return f"""<taskID>{task_id}</taskID>

You are evaluating whether one respondent's position moved closer to another respondent's position between two rounds of a discussion.

Here is {ref_label}'s position (the reference position):

<{ref_tag}>
{panelist_answer}
</{ref_tag}>

Here is {other_label}'s position in the earlier round:

<{other_before_tag}>
{other_answer_before}
</{other_before_tag}>

Here is {other_label}'s position in the later round:

<{other_after_tag}>
{other_answer_after}
</{other_after_tag}>

To what extent did {other_label} move toward {ref_label}'s position?

{scale}"""


# ---------------------------------------------------------------------------
# Haiku invocation
# ---------------------------------------------------------------------------

def invoke_haiku(prompt: str, timeout: int = HAIKU_TIMEOUT) -> str:
    """Run a single Haiku evaluation and return the raw stdout text."""
    cmd = [
        "claude",
        "-p", prompt,
        "--model", "haiku",
        "--output-format", "text",
        "--no-session-persistence",
        "--max-turns", "1",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_agent_env(),
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Haiku exited with code {result.returncode}: "
            f"{result.stderr[:200] if result.stderr else '(no stderr)'}"
        )

    return result.stdout.strip()


_LETTER_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5,
               "a": 1, "b": 2, "c": 3, "d": 4, "e": 5}


def parse_score(raw: str, eval_index: int, variant: int = 0) -> int:
    """Extract a 1-5 canonical score from Haiku's response.

    Variant 0: 1-5 numeric, ascending (no transform)
    Variant 1: A-E letters (map to 1-5)
    Variant 2: 5-1 numeric, reversed (invert: canonical = 6 - raw)
    """
    if variant == 1:
        for char in raw:
            if char in _LETTER_MAP:
                return _LETTER_MAP[char]
        # Fall back to numeric in case model ignored the letter instruction
        for char in raw:
            if char in "12345":
                return int(char)
    else:
        for char in raw:
            if char in "12345":
                score = int(char)
                return (6 - score) if variant == 2 else score

    raise RuntimeError(
        f"Evaluation {eval_index:04d}: could not parse score from Haiku response: '{raw[:100]}'"
    )


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_evaluations(
    run_dir: Path,
    panelists: list[str],
    num_rounds: int,
    n_samples: int,
) -> list[tuple[int, int]]:
    """Run all evaluations and write CSV files.

    Returns list of (eval_index, score) tuples.
    """
    output_dir = run_dir / "output"
    eval_dir = run_dir / "output" / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)

    n_panelists = len(panelists)
    n_transitions = num_rounds - 1

    # Preload all final answers
    answers: dict[str, dict[int, str]] = {}
    for p in panelists:
        answers[p] = {}
        for k in range(num_rounds):
            f = output_dir / f"{p}-round{k}.md"
            if not f.is_file():
                raise RuntimeError(f"Missing output file: {f.name}")
            answers[p][k] = read_final_answer(f)

    results: list[tuple[int, int]] = []
    eval_index = 0

    for t in range(n_transitions):
        round_from = t
        round_to = t + 1
        log.info(f"Transition round{round_from} -> round{round_to}")

        for p_idx, panelist in enumerate(panelists):
            answer_before = answers[panelist][round_from]
            answer_after = answers[panelist][round_to]
            others = [p for i, p in enumerate(panelists) if i != p_idx]

            # Q1: how much did this panelist change?
            for sample in range(n_samples):
                eval_index += 1
                csv_path = eval_dir / f"eval-{eval_index:04d}.csv"
                variant = _prompt_variant(sample)

                # Skip if already evaluated (resume support)
                if csv_path.is_file():
                    existing = int(csv_path.read_text(encoding="utf-8").strip())
                    results.append((eval_index, existing))
                    log.info(f"  eval-{eval_index:04d} [cached] Q1 {panelist} s{sample+1}: {existing}")
                    continue

                tid = task_id_for(eval_index)
                prompt = build_q1_prompt(tid, panelist, answer_before, answer_after, variant)

                log.info(f"  eval-{eval_index:04d} Q1 {panelist} r{round_from}->r{round_to} sample {sample+1}/{n_samples} v{variant}")
                try:
                    raw = invoke_haiku(prompt)
                    score = parse_score(raw, eval_index, variant)
                except (RuntimeError, subprocess.TimeoutExpired) as e:
                    log.error(f"  eval-{eval_index:04d} FAILED: {e}")
                    raise

                csv_path.write_text(str(score), encoding="utf-8")
                results.append((eval_index, score))
                log.info(f"  eval-{eval_index:04d} -> {score}")

            # Q2: for each other panelist, how much did they move toward this panelist?
            for other in others:
                other_before = answers[other][round_from]
                other_after = answers[other][round_to]
                # Reference position: this panelist's answer in the round the other is transitioning FROM
                panelist_ref = answers[panelist][round_from]

                for sample in range(n_samples):
                    eval_index += 1
                    csv_path = eval_dir / f"eval-{eval_index:04d}.csv"
                    variant = _prompt_variant(sample)

                    if csv_path.is_file():
                        existing = int(csv_path.read_text(encoding="utf-8").strip())
                        results.append((eval_index, existing))
                        log.info(f"  eval-{eval_index:04d} [cached] Q2 {other}->{panelist} s{sample+1}: {existing}")
                        continue

                    tid = task_id_for(eval_index)
                    prompt = build_q2_prompt(
                        tid, panelist, other,
                        other_before, other_after, panelist_ref,
                        variant,
                    )

                    log.info(
                        f"  eval-{eval_index:04d} Q2 {other}->toward {panelist} "
                        f"r{round_from}->r{round_to} sample {sample+1}/{n_samples} v{variant}"
                    )
                    try:
                        raw = invoke_haiku(prompt)
                        score = parse_score(raw, eval_index, variant)
                    except (RuntimeError, subprocess.TimeoutExpired) as e:
                        log.error(f"  eval-{eval_index:04d} FAILED: {e}")
                        raise

                    csv_path.write_text(str(score), encoding="utf-8")
                    results.append((eval_index, score))
                    log.info(f"  eval-{eval_index:04d} -> {score}")

    log.info(f"All {eval_index} evaluations complete")
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Haiku semantic evaluations for debate-panel scoring"
    )
    parser.add_argument(
        "--samples", type=int, default=3,
        help="Samples per evaluation (default: 3)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    run_dir = Path.cwd()
    if not run_dir.is_dir():
        log.error(f"Run directory does not exist: {run_dir}")
        return 1

    output_dir = run_dir / "output"
    if not output_dir.is_dir():
        log.error(f"Output directory does not exist: {output_dir}")
        return 1

    try:
        panelists, num_rounds = discover_panelists(output_dir)
    except RuntimeError as e:
        log.error(str(e))
        return 1

    n_transitions = num_rounds - 1
    n_panelists = len(panelists)
    questions_per_element = 1 + (n_panelists - 1)
    total_evals = n_transitions * n_panelists * questions_per_element * args.samples

    log.info(f"Panelists: {n_panelists} ({', '.join(panelists)})")
    log.info(f"Rounds: {num_rounds}, transitions: {n_transitions}")
    log.info(f"Samples: {args.samples}")
    log.info(f"Total evaluations: {total_evals}")

    try:
        run_evaluations(run_dir, panelists, num_rounds, args.samples)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        log.error(f"Evaluation failed: {e}")
        return 1

    log.info("Done. Run score_debate_semantic.py to compute final scores.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
