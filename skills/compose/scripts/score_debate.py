#!/usr/bin/env python3
"""Free-MAD scoring algorithm for the debate-panel pattern.

Reads panelist output files from a run directory, extracts answers from
each round, scores them using the Free-MAD trajectory-tracking algorithm,
and writes the winning answer to output/final-selection.md.

Usage:
    python score_debate.py <run_dir>
    python score_debate.py <run_dir> --semantic   (not yet implemented)
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W1 = 20   # initial appearance credit (round 0)
W2 = 25   # abandonment penalty (subtracted from old answer)
W3 = 30   # conversion reward (added to new answer)
W4 = 20   # maintenance credit (same answer retained)

OUTPUT_DIR = "output"
FINAL_SELECTION_FILE = "output/final-selection.md"
SCORE_DETAILS_FILE = "output/score-details.json"

ROUND_FILE_PATTERN = re.compile(r"^(.+)-round(\d+)\.md$")
FINAL_ANSWER_HEADING = re.compile(r"^##\s+Final\s+Answer\s*$", re.IGNORECASE)

log = logging.getLogger("score_debate")


# ---------------------------------------------------------------------------
# Answer normalization
# ---------------------------------------------------------------------------

def normalize_answer(text: str) -> str:
    """Normalize an answer for comparison.

    - Strip leading/trailing whitespace
    - Collapse runs of whitespace to a single space
    - Lowercase
    """
    return re.sub(r"\s+", " ", text.strip()).lower()


# ---------------------------------------------------------------------------
# File discovery and parsing
# ---------------------------------------------------------------------------

def discover_round_files(output_dir: Path) -> dict[str, dict[int, Path]]:
    """Find all panelist round files and organize by persona and round.

    Returns:
        {persona: {round_number: file_path}}
    """
    if not output_dir.is_dir():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    roster: dict[str, dict[int, Path]] = defaultdict(dict)

    for entry in sorted(output_dir.iterdir()):
        if not entry.is_file():
            continue
        match = ROUND_FILE_PATTERN.match(entry.name)
        if not match:
            continue
        persona = match.group(1)
        round_num = int(match.group(2))
        roster[persona][round_num] = entry

    return dict(roster)


def extract_final_answer(file_path: Path) -> str:
    """Extract the text after the '## Final Answer' heading.

    Returns the raw (pre-normalization) answer text.
    Raises ValueError if the heading is not found or the section is empty.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read {file_path}: {e}") from e

    lines = content.splitlines()
    heading_index = None

    for i, line in enumerate(lines):
        if FINAL_ANSWER_HEADING.match(line.strip()):
            heading_index = i
            # Don't break -- use the LAST occurrence if there are duplicates

    if heading_index is None:
        raise ValueError(
            f"No '## Final Answer' heading found in {file_path.name}"
        )

    answer_lines = lines[heading_index + 1:]
    answer_text = "\n".join(answer_lines).strip()

    if not answer_text:
        raise ValueError(
            f"Empty '## Final Answer' section in {file_path.name}"
        )

    return answer_text


# ---------------------------------------------------------------------------
# Answer matrix construction
# ---------------------------------------------------------------------------

def build_answer_matrix(
    roster: dict[str, dict[int, Path]],
) -> tuple[list[str], int, dict[str, dict[int, str]], dict[str, dict[int, str]]]:
    """Build the answer matrix from discovered files.

    Returns:
        personas:      sorted list of persona names
        num_rounds:     total number of rounds (R+1, counting from 0)
        raw_answers:    {persona: {round: raw_answer_text}}
        norm_answers:   {persona: {round: normalized_answer_text}}
    """
    if not roster:
        raise RuntimeError("No panelist round files found")

    personas = sorted(roster.keys())

    # Determine round range
    all_rounds: set[int] = set()
    for rounds in roster.values():
        all_rounds.update(rounds.keys())

    if not all_rounds:
        raise RuntimeError("No rounds found in panelist files")

    min_round = min(all_rounds)
    max_round = max(all_rounds)

    if min_round != 0:
        raise RuntimeError(
            f"Expected rounds to start at 0, but minimum round is {min_round}"
        )

    num_rounds = max_round + 1

    # Validate completeness: every persona should have every round
    raw_answers: dict[str, dict[int, str]] = {}
    norm_answers: dict[str, dict[int, str]] = {}

    for persona in personas:
        raw_answers[persona] = {}
        norm_answers[persona] = {}
        for k in range(num_rounds):
            if k not in roster[persona]:
                raise RuntimeError(
                    f"Missing file for persona '{persona}' round {k}. "
                    f"Expected: {persona}-round{k}.md"
                )
            raw = extract_final_answer(roster[persona][k])
            raw_answers[persona][k] = raw
            norm_answers[persona][k] = normalize_answer(raw)

    return personas, num_rounds, raw_answers, norm_answers


# ---------------------------------------------------------------------------
# Free-MAD scoring
# ---------------------------------------------------------------------------

def score_answers(
    personas: list[str],
    num_rounds: int,
    norm_answers: dict[str, dict[int, str]],
) -> tuple[dict[str, float], list[dict]]:
    """Run the Free-MAD scoring algorithm.

    Returns:
        scores:   {normalized_answer: accumulated_score}
        events:   list of scoring event dicts for the detail log
    """
    scores: dict[str, float] = defaultdict(float)
    events: list[dict] = []

    for k in range(num_rounds):
        f = 1.0 / (k + 1)  # round decay factor

        for persona in personas:
            current = norm_answers[persona][k]

            if k == 0:
                delta = W1 * f
                scores[current] += delta
                events.append({
                    "round": k,
                    "persona": persona,
                    "event": "initial_appearance",
                    "answer": current,
                    "weight": W1,
                    "decay": f,
                    "delta": delta,
                })
            else:
                previous = norm_answers[persona][k - 1]

                if current != previous:
                    # Abandonment penalty on old answer
                    penalty = W2 * f
                    scores[previous] -= penalty
                    events.append({
                        "round": k,
                        "persona": persona,
                        "event": "abandonment",
                        "answer": previous,
                        "weight": W2,
                        "decay": f,
                        "delta": -penalty,
                    })

                    # Conversion reward on new answer
                    reward = W3 * f
                    scores[current] += reward
                    events.append({
                        "round": k,
                        "persona": persona,
                        "event": "conversion",
                        "answer": current,
                        "weight": W3,
                        "decay": f,
                        "delta": reward,
                    })
                else:
                    # Maintenance credit
                    credit = W4 * f
                    scores[current] += credit
                    events.append({
                        "round": k,
                        "persona": persona,
                        "event": "maintenance",
                        "answer": current,
                        "weight": W4,
                        "decay": f,
                        "delta": credit,
                    })

    return dict(scores), events


def select_winner(
    scores: dict[str, float],
) -> tuple[str, float]:
    """Select the winning normalized answer. Ties broken randomly."""
    if not scores:
        raise RuntimeError("No scores computed -- nothing to select")

    max_score = max(scores.values())
    tied = [ans for ans, s in scores.items() if s == max_score]

    winner = random.choice(tied)
    return winner, max_score


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def find_verbatim_answer(
    winner_norm: str,
    personas: list[str],
    num_rounds: int,
    raw_answers: dict[str, dict[int, str]],
    norm_answers: dict[str, dict[int, str]],
) -> tuple[str, list[dict]]:
    """Find the verbatim (pre-normalization) text for the winning answer.

    Prefers the latest round from any persona that held this answer.
    Also returns a list of all (persona, round) occurrences.
    """
    occurrences: list[dict] = []
    verbatim = ""

    for k in range(num_rounds):
        for persona in personas:
            if norm_answers[persona][k] == winner_norm:
                occurrences.append({"persona": persona, "round": k})
                verbatim = raw_answers[persona][k]

    return verbatim, occurrences


def write_final_selection(
    run_dir: Path,
    scores: dict[str, float],
    winner_norm: str,
    winner_score: float,
    verbatim: str,
    occurrences: list[dict],
    personas: list[str],
    num_rounds: int,
    norm_answers: dict[str, dict[int, str]],
) -> Path:
    """Write output/final-selection.md."""
    out_path = run_dir / FINAL_SELECTION_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_answers = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    lines: list[str] = []
    lines.append("# Debate Panel Result")
    lines.append("")
    lines.append("## Scoring Summary")
    lines.append("")
    lines.append(f"- **Panelists:** {len(personas)} ({', '.join(personas)})")
    lines.append(f"- **Rounds:** {num_rounds} (0 through {num_rounds - 1})")
    lines.append(f"- **Unique answers scored:** {len(scores)}")
    lines.append("")
    lines.append("| Rank | Score | Answer (normalized, truncated) |")
    lines.append("|------|-------|-------------------------------|")

    for rank, (ans, score) in enumerate(sorted_answers, 1):
        display = ans[:80] + ("..." if len(ans) > 80 else "")
        marker = " **(winner)**" if ans == winner_norm else ""
        lines.append(f"| {rank} | {score:+.2f} | {display}{marker} |")

    lines.append("")
    lines.append("## Answer Trajectory")
    lines.append("")

    for persona in personas:
        trajectory = []
        for k in range(num_rounds):
            ans = norm_answers[persona][k]
            short = ans[:50] + ("..." if len(ans) > 50 else "")
            trajectory.append(f"R{k}: {short}")
        lines.append(f"- **{persona}:** {' -> '.join(trajectory)}")

    lines.append("")
    lines.append("## Winning Answer Holders")
    lines.append("")

    for occ in occurrences:
        lines.append(f"- **{occ['persona']}** in round {occ['round']}")

    lines.append("")
    lines.append("## Final Answer")
    lines.append("")
    lines.append(verbatim)
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_score_details(
    run_dir: Path,
    scores: dict[str, float],
    events: list[dict],
    winner_norm: str,
    winner_score: float,
    occurrences: list[dict],
    personas: list[str],
    num_rounds: int,
    norm_answers: dict[str, dict[int, str]],
    raw_answers: dict[str, dict[int, str]],
) -> Path:
    """Write output/score-details.json."""
    out_path = run_dir / SCORE_DETAILS_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build per-answer detail
    answer_details: list[dict] = []
    for ans, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        holders = []
        for k in range(num_rounds):
            for persona in personas:
                if norm_answers[persona][k] == ans:
                    holders.append({"persona": persona, "round": k})
        answer_details.append({
            "normalized_answer": ans,
            "score": round(score, 4),
            "is_winner": ans == winner_norm,
            "held_by": holders,
        })

    # Build answer matrix for the JSON output
    matrix: dict[str, list[str]] = {}
    for persona in personas:
        matrix[persona] = [
            norm_answers[persona][k] for k in range(num_rounds)
        ]

    detail = {
        "algorithm": "free-mad",
        "weights": {"w1": W1, "w2": W2, "w3": W3, "w4": W4},
        "personas": personas,
        "num_rounds": num_rounds,
        "answer_matrix_normalized": matrix,
        "scores": {ans: round(s, 4) for ans, s in scores.items()},
        "winner": {
            "normalized_answer": winner_norm,
            "score": round(winner_score, 4),
            "occurrences": occurrences,
        },
        "events": events,
        "answers": answer_details,
    }

    out_path.write_text(
        json.dumps(detail, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Free-MAD scoring for debate-panel runs"
    )
    parser.add_argument(
        "run_dir",
        help="Path to the run directory containing output/{persona}-round{k}.md files",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Use semantic equivalence for answer comparison (not yet implemented)",
    )
    args = parser.parse_args()

    # Configure logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if args.semantic:
        log.info(
            "--semantic flag received but semantic equivalence is not yet "
            "implemented. Falling back to exact normalized string match."
        )

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        log.error(f"Run directory does not exist: {run_dir}")
        return 1

    output_dir = run_dir / OUTPUT_DIR
    if not output_dir.is_dir():
        log.error(f"Output directory does not exist: {output_dir}")
        return 1

    # Discover files
    try:
        roster = discover_round_files(output_dir)
    except FileNotFoundError as e:
        log.error(str(e))
        return 1

    if not roster:
        log.error(
            f"No panelist round files found matching pattern "
            f"'{{persona}}-round{{k}}.md' in {output_dir}"
        )
        return 1

    log.info(
        f"Found {len(roster)} persona(s): {', '.join(sorted(roster.keys()))}"
    )

    # Build answer matrix
    try:
        personas, num_rounds, raw_answers, norm_answers = build_answer_matrix(roster)
    except (RuntimeError, ValueError) as e:
        log.error(f"Failed to build answer matrix: {e}")
        return 1

    log.info(f"Answer matrix: {len(personas)} personas x {num_rounds} rounds")

    # Score
    scores, events = score_answers(personas, num_rounds, norm_answers)
    log.info(f"Scored {len(scores)} unique answer(s)")

    for ans, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        display = ans[:60] + ("..." if len(ans) > 60 else "")
        log.info(f"  {score:+.2f}  {display}")

    # Select winner
    winner_norm, winner_score = select_winner(scores)
    log.info(f"Winner (score={winner_score:+.2f}): {winner_norm[:80]}")

    # Find verbatim answer
    verbatim, occurrences = find_verbatim_answer(
        winner_norm, personas, num_rounds, raw_answers, norm_answers
    )

    # Write outputs
    try:
        sel_path = write_final_selection(
            run_dir, scores, winner_norm, winner_score, verbatim,
            occurrences, personas, num_rounds, norm_answers,
        )
        log.info(f"Wrote {sel_path}")

        det_path = write_score_details(
            run_dir, scores, events, winner_norm, winner_score,
            occurrences, personas, num_rounds, norm_answers, raw_answers,
        )
        log.info(f"Wrote {det_path}")

    except OSError as e:
        log.error(f"Failed to write output: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
