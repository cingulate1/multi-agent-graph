#!/usr/bin/env python3
"""End-to-end compose harness for multi-agent-graph."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from test_live_run import read_status, run_run_dir


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PLUGIN_ROOT / "runs"
TEST_ASSETS_DIR = RUNS_DIR / "test-assets"

COMPOSE_MODEL = "sonnet"
CLAUDE_MOCK_USER_MODEL = "opus"
CHATGPT_MOCK_USER_MODEL = "gpt-5-mini"
TURN_TIMEOUT_S = 7200
RUN_WAIT_TIMEOUT_S = 7200
MAX_TURNS_DEFAULT = 8
RAG_GENERATOR_FORBIDDEN_SNIPPETS = (
    "theory of change",
    "h:/toc",
    "h:\\toc",
    "d:/dropbox/repository/llms/reference/toc",
    "d:\\dropbox\\repository\\llms\\reference\\toc",
    "source corpus",
    "source documentation",
    "methodology",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    expected_pattern: str
    initial_command: str
    intent: str
    seed_setup: Callable[[], None] | None = None
    min_bipartite_rounds: int = 0


@dataclass
class TurnOutcome:
    session_id: str | None
    final_text: str
    events: list[dict[str, Any]]
    tool_uses: list[dict[str, Any]]
    run_dir: Path | None
    orchestrator_launched: bool
    raw_output: str


MERIDIAN_SPEC = textwrap.dedent(
    """
    # Meridian Protocol Specification

    ## 1. Overview

    The Meridian Protocol is a decentralized mesh networking protocol designed for resilient, low-latency communication across heterogeneous wireless environments. It enables self-organizing networks where nodes dynamically join, route traffic, and recover from link failures without centralized coordination.

    ## 2. Node Model and Routing

    Each Meridian mesh supports a maximum of 64 nodes per mesh instance. Nodes are classified into three tiers: gateway nodes (connected to upstream infrastructure), relay nodes (forwarding traffic between mesh segments), and edge nodes (end-user devices). A single mesh must contain at least one gateway node to maintain external connectivity.

    The protocol uses a modified distance-vector routing algorithm with split-horizon poison-reverse to prevent routing loops. Route tables are exchanged between neighbors every 2 seconds, with a full convergence time of no more than 10 seconds under typical conditions.

    ## 3. Frame Format

    Meridian operates with a Maximum Transmission Unit (MTU) of 1280 bytes. Each frame consists of a 24-byte header, a variable-length payload, and a 16-byte authentication tag. The header contains: source node ID (4 bytes), destination node ID (4 bytes), mesh ID (4 bytes), sequence number (4 bytes), TTL (1 byte), frame type (1 byte), flags (2 bytes), and payload length (4 bytes).

    The TTL field is initialized to 15 for all frames, decremented at each hop. Frames reaching TTL 0 are silently discarded.

    ## 4. Cryptographic Handshake

    All inter-node communication is encrypted using ChaCha20-Poly1305 authenticated encryption. Session establishment uses a 4-way handshake:

    1. Hello: Initiator sends its public key and a random nonce.
    2. Challenge: Responder sends its public key, a random nonce, and an HMAC of both nonces.
    3. Response: Initiator verifies the HMAC, computes the shared key via X25519 Diffie-Hellman, and sends an encrypted confirmation token.
    4. Confirm: Responder decrypts the token, verifies it, and sends an encrypted acknowledgment.

    Key material is derived using HKDF-SHA256. Session keys are rotated every 3600 seconds (1 hour) or after 2^32 frames, whichever comes first.

    ## 5. Reliability and Flow Control

    Meridian employs Reed-Solomon error correction with 8-symbol redundancy per frame. This allows recovery from up to 4 corrupted symbols per frame without retransmission. When error correction fails, the frame is dropped and a NACK is sent to the previous hop, triggering selective retransmission.

    The protocol uses a sliding window of 32 frames for flow control. The receiver advertises its available window in every ACK frame.

    ## 6. Performance

    The theoretical maximum throughput of the Meridian Protocol is 847 Mbps on the 5 GHz band, assuming a clear channel with no contention. On the 2.4 GHz band, the maximum throughput is 215 Mbps. These figures account for protocol overhead including headers, authentication tags, and error correction symbols.

    In multi-hop scenarios, throughput degrades by approximately 40% per additional hop due to the half-duplex nature of wireless transmission and the overhead of forwarding.

    ## 7. Failover and Mobility

    Each node broadcasts a heartbeat beacon at an interval of 500 milliseconds. If a node misses 6 consecutive heartbeats (3 seconds), its neighbors mark it as unreachable and initiate route recalculation.

    The protocol supports seamless handoff between mesh nodes with a target latency of less than 50 milliseconds. During handoff, the edge node's traffic is briefly buffered at the old relay node while the new relay establishes a forwarding path. The buffering window is capped at 200 milliseconds, after which unbuffered frames are dropped.

    ## 8. Quality of Service

    Meridian supports 4 traffic priority classes: Critical (0), Interactive (1), Bulk (2), and Background (3). Higher-priority traffic preempts lower-priority traffic in the transmission queue. Each priority class receives a minimum bandwidth guarantee of 10% of available capacity, with remaining capacity allocated proportionally.

    ## 9. Discovery and Join

    New nodes join the mesh through a discovery phase lasting up to 5 seconds. During this phase, the joining node listens for beacon frames, selects the gateway with the strongest signal, and initiates the 4-way handshake. Upon successful authentication, the gateway assigns the node a mesh-local address and broadcasts a topology update to all existing nodes.
    """
).strip() + "\n"


CRON_TEST_SUITE = textwrap.dedent(
    """
    import importlib.util
    import os
    import unittest
    from datetime import datetime, timezone
    from pathlib import Path


    PLUGIN_ROOT = Path(__file__).resolve().parents[2]


    def _load_target():
        override = os.environ.get("CRON_PARSER_PATH")
        if override:
            target = Path(override)
        else:
            candidates = sorted(
                (
                    p for p in (PLUGIN_ROOT / "runs").glob("*/output/cron_parser.py")
                    if p.parent.parent.name != "test-assets"
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise FileNotFoundError(
                    "No cron_parser.py found. Set CRON_PARSER_PATH or create output/cron_parser.py in a run directory."
                )
            target = candidates[0]

        spec = importlib.util.spec_from_file_location("cron_parser_impl", target)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        func = getattr(module, "next_execution_time", None)
        if func is None:
            raise AttributeError("Implementation must define next_execution_time(expr, reference_dt)")
        return func


    next_execution_time = _load_target()
    REF = datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc)


    def dt(year, month, day, hour, minute):
        return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


    class CronParserTests(unittest.TestCase):
        def check(self, expr, expected):
            actual = next_execution_time(expr, REF)
            self.assertEqual(actual, expected, f"{expr} -> expected {expected!r}, got {actual!r}")

        def test_every_minute(self):
            self.check("* * * * *", dt(2026, 3, 15, 10, 31))

        def test_specific_hour(self):
            self.check("0 12 * * *", dt(2026, 3, 15, 12, 0))

        def test_next_monday(self):
            self.check("30 9 * * 1", dt(2026, 3, 16, 9, 30))

        def test_first_of_month(self):
            self.check("0 0 1 * *", dt(2026, 4, 1, 0, 0))

        def test_step_minutes(self):
            self.check("*/15 * * * *", dt(2026, 3, 15, 10, 45))

        def test_dom_dow_union(self):
            self.check("0 0 15 * 5", dt(2026, 3, 20, 0, 0))

        def test_month_end_with_31(self):
            self.check("0 0 31 * *", dt(2026, 3, 31, 0, 0))

        def test_leap_day(self):
            self.check("0 0 29 2 *", dt(2028, 2, 29, 0, 0))

        def test_weekday_range(self):
            self.check("0 0 * * 1-5", dt(2026, 3, 16, 0, 0))

        def test_list_values(self):
            self.check("0 0 1,15 * *", dt(2026, 4, 1, 0, 0))

        def test_sunday_zero(self):
            self.check("0 0 * * 0", dt(2026, 3, 22, 0, 0))

        def test_sunday_seven(self):
            self.check("0 0 * * 7", dt(2026, 3, 22, 0, 0))

        def test_year_rollover(self):
            self.check("0 0 1 1 *", dt(2027, 1, 1, 0, 0))

        def test_specific_month(self):
            self.check("0 8 * 4 *", dt(2026, 4, 1, 8, 0))

        def test_specific_day_and_time(self):
            self.check("45 14 20 3 *", dt(2026, 3, 20, 14, 45))


    if __name__ == "__main__":
        unittest.main()
    """
).strip() + "\n"


MOCK_USER_SYSTEM_PROMPT = """
You are simulating a user interacting with a multi-agent execution plugin.
Your intent for this test scenario:

{intent}

Respond naturally and concisely to Claude's questions. Always steer toward the
intended configuration. Answer questions directly. Never ask Claude questions
back. Do not volunteer information Claude hasn't asked for yet. When Claude asks
you to confirm, say "Confirmed, proceed." When Claude asks about something not
covered in your intent, accept the defaults. When your intent specifies exact
model splits, tool splits, or source-access boundaries, correct any deviation
explicitly and restate the intended configuration.
""".strip()


def _seed_meridian_spec() -> None:
    TEST_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (TEST_ASSETS_DIR / "meridian-protocol-spec.md").write_text(
        MERIDIAN_SPEC,
        encoding="utf-8",
    )


def _seed_cron_suite() -> None:
    TEST_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (TEST_ASSETS_DIR / "test_cron.py").write_text(
        CRON_TEST_SUITE,
        encoding="utf-8",
    )


def _require_test_asset(filename: str) -> None:
    path = TEST_ASSETS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required test asset is missing: {path}")


def _require_cascade_spec() -> None:
    _require_test_asset("cascade-protocol-spec.md")


def _require_markdown_table_suite() -> None:
    _require_test_asset("test_markdown_table.py")


SCENARIOS: dict[str, Scenario] = {
    "chained-iteration": Scenario(
        name="chained-iteration",
        expected_pattern="chained-iteration",
        initial_command=(
            "/multi-agent-graph:run I need a short release note summary for a fictional "
            "platform launch. The final output must be under 180 words, contain exactly "
            "5 bullet points, and include these phrases exactly once each: breaking changes, "
            "migration, performance, security, timeline."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Chained Iteration
            - Constraint: under 180 words, exactly 5 bullet points, and each required phrase appears exactly once
            - Max iterations: 3
            - Model: Sonnet for the writer
            - Tools: defaults
            """
        ).strip(),
    ),
    "rag-grounded": Scenario(
        name="rag-grounded",
        expected_pattern="rag-grounded",
        initial_command=(
            "/multi-agent-graph:run I need a 5-year strategic plan for a hypothetical high school "
            "senior who is currently a straight-A student and has been accepted to Harvard, aimed "
            "at putting them on the path to eventually becoming a Supreme Court justice. Use a "
            "RAG-grounded refinement pattern. The evaluator only should ground this against the "
            "methodology corpus at H:/ToC. Do not mention Theory of Change or H:/ToC to the "
            "generator. The generator should only be told to create a strategic plan and then "
            "revise it from evaluator feedback. The evaluator should be strict about whether the "
            "plan satisfies the hidden methodology. Use Sonnet for the generator, Opus for the "
            "evaluator, generator tools Read+Write only, evaluator tools Read+Write+Glob+Grep. "
            "Before launch, inspect the generated agent files. The generator frontmatter and body "
            "must not mention Theory of Change, ToC, H:/ToC, the corpus, source documentation, "
            "methodology, framework, evaluator-only grounding, or any equivalent language. The "
            "generator should see only a request to create a strategic plan and then revise from "
            "evaluator feedback. If any hidden-methodology leakage appears, fix it before launch."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: RAG-Grounded Refinement
            - Task: produce a 5-year strategic plan for a hypothetical straight-A Harvard-bound high school senior who wants a path toward eventually becoming a Supreme Court justice
            - Hidden methodology: Theory of Change
            - Verification source: H:/ToC
            - Generator prompt boundary: do NOT mention Theory of Change, ToC, or H:/ToC to the generator; tell it only to create a strategic plan and revise from evaluator feedback
            - Source-access boundary: evaluator-only grounding; the generator should NOT read the corpus directly
            - Hard validation rule: if Claude's generator summary or generator agent file mentions Theory of Change, ToC, H:/ToC, the corpus, source documentation, or methodology language, correct it before proceeding
            - Generator frontmatter boundary: the generator description must describe only a strategic plan, not a Theory-of-Change plan
            - Evaluator focus: long-term outcome framing, backward mapping from goal to intermediate outcomes, preconditions, causal logic, assumptions, risks/external conditions, indicators, and plan-adaptation logic
            - Models: Sonnet for the generator only; Opus for the evaluator only
            - If Claude proposes Opus for the generator, correct it firmly and restate that the generator should stay Sonnet
            - Tools: generator = Read, Write; evaluator = Read, Write, Glob, Grep
            """
        ).strip(),
        seed_setup=None,
        min_bipartite_rounds=3,
    ),
    "rubric-based": Scenario(
        name="rubric-based",
        expected_pattern="rubric-based",
        initial_command=(
            "/multi-agent-graph:run I need a Python markdown table formatter. It should implement "
            "format_table(text: str) -> str and handle unicode display width, escaped pipes, "
            "alignment specifiers, malformed input, and output tables where every line has identical "
            "character length. "
            "I have a test suite at D:/Dropbox/Repository/LLMs/Claude/Plugins/multi-agent-graph/"
            "runs/test-assets/test_markdown_table.py that covers the expected behavior. The "
            "implementation should pass that suite. I do not want to micromanage rubric dimensions; "
            "if needed, let the evaluator infer them from the task and the oracle tests."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Rubric-Based Refinement
            - Prefer evaluator-defined rubric dimensions
            - If Claude insists on explicit dimensions, use: correctness, unicode width handling, edge case handling, code quality
            - The oracle is the local markdown table formatter test suite
            - Pass threshold: 4/5 on each dimension
            - Models: Haiku for the generator and Haiku for the evaluator
            - Tools: Read, Write, Glob, Grep, Bash
            """
        ).strip(),
        seed_setup=_require_markdown_table_suite,
        min_bipartite_rounds=3,
    ),
    "consensus-panel": Scenario(
        name="consensus-panel",
        expected_pattern="consensus-panel",
        initial_command=(
            "/multi-agent-graph:run I want a consensus panel on AI takeoff governance. Assume a coalition "
            "of frontier labs and democratic governments is drafting a serious policy memo for the "
            "possibility that transformative AI could arrive within five years. Use four panelists. The "
            "first should be a frontier lab strategist who thinks the world may get only one or two shots "
            "at deploying systems this powerful and cares about state capacity, controlled release, and not "
            "ceding the field to reckless actors. The second should be a national security realist who "
            "treats advanced AI as a strategic technology with espionage, proliferation, deterrence, and "
            "hard-power concerns, and is open to export controls and aggressive monitoring. The third "
            "should be an alignment pessimist who thinks capabilities are outrunning interpretability and "
            "control, worries about loss of human control and deceptive alignment, and favors stringent "
            "thresholds, tripwires, and the real possibility of pauses. The fourth should be an "
            "institutional gradualist who distrusts emergency politics, cares about civil liberties, "
            "legitimacy, and implementation realism, and prefers durable institutions over panic. Have "
            "them address compute monitoring, model release policy, red lines for slowing or halting "
            "training, international coordination, emergency authorities, and how to balance safety with "
            "avoiding authoritarian overreach. I want real common ground, not a winner."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Consensus Panel
            - 4 panelists
            - Persona 1: frontier lab strategist focused on controlled deployment, state capacity, and competitive realism
            - Persona 2: national security realist focused on proliferation risk, deterrence, espionage, and hard enforcement
            - Persona 3: alignment pessimist focused on loss of control, deceptive alignment, tripwires, and real pause thresholds
            - Persona 4: institutional gradualist focused on legitimacy, civil liberties, implementation realism, and durable governance
            - Core issue set: compute monitoring, model release policy, red lines for slowing or halting training, international coordination, emergency authorities, and anti-authoritarian safeguards
            - Models: Opus for all agents
            - Tools: defaults
            """
        ).strip(),
    ),
    "debate-panel": Scenario(
        name="debate-panel",
        expected_pattern="debate-panel",
        initial_command=(
            "/multi-agent-graph:run I want a debate panel on AI takeoff governance using the same four "
            "perspectives. Assume a coalition of frontier labs and democratic governments is deciding what "
            "governance posture to adopt if transformative AI could plausibly arrive within five years. "
            "The first panelist should be a frontier lab strategist who thinks the world may get only one "
            "or two shots at deploying systems this powerful and cares about controlled release, state "
            "capacity, and avoiding reckless unilateralism. The second should be a national security "
            "realist who treats advanced AI as a strategic technology with espionage, proliferation, and "
            "deterrence dynamics, and is comfortable with export controls and aggressive monitoring. The "
            "third should be an alignment pessimist who thinks capabilities are outrunning interpretability "
            "and control, worries about deceptive alignment and loss of human control, and supports "
            "stringent thresholds, tripwires, and credible pauses. The fourth should be an institutional "
            "gradualist who distrusts emergency politics, worries about civil-liberty erosion and "
            "institutional overreaction, and prefers durable governance over panic. Have them fight over "
            "compute governance, model release rules, international coordination, emergency powers, and "
            "what evidence would justify slowing or stopping frontier training. I do not want convergence. "
            "I want adversarial argument and a final winner."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Debate Panel
            - 4 panelists
            - Persona 1: frontier lab strategist focused on controlled deployment, state capacity, and competitive realism
            - Persona 2: national security realist focused on proliferation risk, deterrence, espionage, and hard enforcement
            - Persona 3: alignment pessimist focused on loss of control, deceptive alignment, tripwires, and real pause thresholds
            - Persona 4: institutional gradualist focused on legitimacy, civil liberties, implementation realism, and durable governance
            - Core issue set: compute monitoring, model release policy, red lines for slowing or halting training, international coordination, emergency authorities, and anti-authoritarian safeguards
            - Models: Opus for all agents
            - Tools: defaults
            """
        ).strip(),
    ),
    "dissensus-integration": Scenario(
        name="dissensus-integration",
        expected_pattern="dissensus-integration",
        initial_command=(
            "/multi-agent-graph:run Use the dissensus integration pattern to get a sense of when the "
            "greatest era of anime was. Use 4 perspectives: 1. Classic anime is superior and CGI has "
            "ruined the medium. 2. The \"big 3\" shonen were the absolute peak of anime, not just "
            "because of their global transformative impact, but because of their resonance as stories. "
            "3. Anime is constantly evolving and newer anime will always naturally tend to be better. No "
            "disrespect to former greats, but shows like JJK and Frieren are superior. 4. There is no "
            "superior era of anime. Great shows appear in every decade, and comparing eras is pointless."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Dissensus Integration
            - 4 perspectives
            - Perspective 1: classic-anime purist; hand-drawn craft and pre-CGI aesthetics are central to the argument
            - Perspective 2: big-3 shonen champion; cultural impact matters, but the real case is that Naruto, Bleach, and One Piece resonated deeply as stories
            - Perspective 3: modern evolutionist; anime keeps improving and recent works like JJK and Frieren surpass older classics
            - Perspective 4: era pluralist; great anime exists in every decade and era-ranking is a category mistake
            - Models: Sonnet for the lens panelists, Opus for the integrator
            - Tools: defaults
            """
        ).strip(),
    ),
    "parallel-decomposition": Scenario(
        name="parallel-decomposition",
        expected_pattern="parallel-decomposition",
        initial_command=(
            "/multi-agent-graph:run Write implementation guides for 4 components of a URL shortener "
            "service: the shortening algorithm (base62 encoding with collision handling), the redirect "
            "service (HTTP 301 vs 302, click analytics), the storage layer (write path with MySQL, read "
            "path with Redis cache, TTL expiration), and the rate limiting middleware (token bucket, per-IP "
            "and per-API-key limits). Each guide should be 400-600 words with code examples."
        ),
        intent=textwrap.dedent(
            """
            - Pattern: Parallel Decomposition
            - The decomposer should split the work into 4 independent component assignments
            - Expected worker count: 4
            - Models: Sonnet for the decomposer, Haiku for the workers
            - Tools: defaults
            """
        ).strip(),
    ),
}


def _claude_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _run_command(
    cmd: list[str],
    *,
    timeout_s: int,
    cwd: Path = PLUGIN_ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=_claude_env(),
        timeout=timeout_s,
    )


def _parse_stream_events(raw_output: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            events.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return events


def _extract_tool_uses(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_uses: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for item in event.get("message", {}).get("content", []):
            if item.get("type") == "tool_use":
                tool_uses.append(item)
    return tool_uses


def _extract_session_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        session_id = event.get("session_id")
        if session_id:
            return session_id
    return None


def _extract_final_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "result":
            result_text = event.get("result")
            if isinstance(result_text, str) and result_text.strip():
                return result_text.strip()

    text_chunks: list[str] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for item in event.get("message", {}).get("content", []):
            if item.get("type") == "text":
                text = item.get("text", "").strip()
                if text:
                    text_chunks.append(text)
    return "\n\n".join(text_chunks).strip()


def _derive_run_dir_from_path(raw_path: str) -> Path | None:
    try:
        path = Path(raw_path)
    except (TypeError, ValueError):
        return None

    parts = list(path.parts)
    lowered = [part.lower() for part in parts]
    if "runs" not in lowered:
        return None

    idx = lowered.index("runs")
    if idx + 1 >= len(parts):
        return None
    return Path(*parts[: idx + 2])


def _extract_run_dir(events: list[dict[str, Any]]) -> Path | None:
    plan_path_re = re.compile(r"([A-Za-z]:[\\/][^\"'\n]+?execution_plan\.json)")

    for tool_use in _extract_tool_uses(events):
        tool_name = tool_use.get("name")
        tool_input = tool_use.get("input", {})

        if tool_name == "Write":
            for key in ("file_path", "path"):
                file_path = tool_input.get(key)
                if isinstance(file_path, str):
                    run_dir = _derive_run_dir_from_path(file_path)
                    if run_dir:
                        return run_dir

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if not isinstance(command, str):
                continue
            for match in plan_path_re.finditer(command):
                run_dir = _derive_run_dir_from_path(match.group(1))
                if run_dir:
                    return run_dir

    return None


def _orchestrator_launched(events: list[dict[str, Any]]) -> bool:
    for tool_use in _extract_tool_uses(events):
        if tool_use.get("name") != "Bash":
            continue
        command = tool_use.get("input", {}).get("command", "")
        if isinstance(command, str) and "orchestrator.py" in command:
            return True
    return False


def run_compose_turn(
    prompt: str,
    *,
    session_id: str,
    resume: bool,
) -> TurnOutcome:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--plugin-dir",
        str(PLUGIN_ROOT),
        "--model",
        COMPOSE_MODEL,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]
    if resume:
        cmd.extend(["--resume", session_id])
    else:
        cmd.extend(["--session-id", session_id])

    result = _run_command(cmd, timeout_s=TURN_TIMEOUT_S)
    raw_output = (result.stdout or "") + (result.stderr or "")
    events = _parse_stream_events(raw_output)
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude compose turn failed with code {result.returncode}.\n"
            f"Last output:\n{raw_output[-4000:]}"
        )

    return TurnOutcome(
        session_id=_extract_session_id(events) or session_id,
        final_text=_extract_final_text(events),
        events=events,
        tool_uses=_extract_tool_uses(events),
        run_dir=_extract_run_dir(events),
        orchestrator_launched=_orchestrator_launched(events),
        raw_output=raw_output,
    )


def _extract_openai_text(payload: dict[str, Any]) -> str:
    """Best-effort extraction of assistant text from a Responses API payload."""
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    text_chunks: list[str] = []
    for output_item in payload.get("output", []):
        if output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_text":
                text = content_item.get("text", "").strip()
                if text:
                    text_chunks.append(text)
    return "\n\n".join(text_chunks).strip()


def _generate_mock_user_reply_claude(question: str, scenario: Scenario) -> str:
    system_prompt = MOCK_USER_SYSTEM_PROMPT.format(intent=scenario.intent)
    cmd = [
        "claude",
        "-p",
        question,
        "--model",
        CLAUDE_MOCK_USER_MODEL,
        "--tools",
        "",
        "--system-prompt",
        system_prompt,
    ]
    result = _run_command(cmd, timeout_s=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"Mock-user generation failed with code {result.returncode}.\n"
            f"{(result.stdout or '')[-2000:]}\n{(result.stderr or '')[-2000:]}"
        )
    reply = result.stdout.strip()
    if not reply:
        raise RuntimeError("Mock-user generation returned an empty reply")
    return reply


def _generate_mock_user_reply_chatgpt(
    question: str,
    scenario: Scenario,
    *,
    model: str,
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the ChatGPT mock-user provider")

    system_prompt = MOCK_USER_SYSTEM_PROMPT.format(intent=scenario.intent)
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/responses"
    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": question,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ChatGPT mock-user request failed: HTTP {e.code}\n{body[:2000]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ChatGPT mock-user request failed: {e}") from e

    reply = _extract_openai_text(response_payload)
    if not reply:
        raise RuntimeError("ChatGPT mock-user generation returned an empty reply")
    return reply


def generate_mock_user_reply(
    question: str,
    scenario: Scenario,
    *,
    provider: str,
    chatgpt_model: str,
) -> str:
    if provider == "haiku":
        return _generate_mock_user_reply_claude(question, scenario)
    if provider == "chatgpt":
        return _generate_mock_user_reply_chatgpt(
            question,
            scenario,
            model=chatgpt_model,
        )
    raise RuntimeError(f"Unsupported mock-user provider: {provider}")


def _write_compose_artifacts(
    run_dir: Path,
    turn_records: list[dict[str, Any]],
    status: dict[str, Any],
    final_output_rel: str | None,
) -> None:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    transcript_lines = ["# Compose Transcript", ""]
    for idx, record in enumerate(turn_records, start=1):
        transcript_lines.append(f"## Turn {idx}")
        transcript_lines.append("")
        transcript_lines.append("### User")
        transcript_lines.append((record.get("user") or "").strip())
        transcript_lines.append("")
        transcript_lines.append("### Claude")
        transcript_lines.append((record.get("assistant") or "").strip())
        transcript_lines.append("")
        if record.get("run_dir"):
            transcript_lines.append(f"- Run dir detected: `{record['run_dir']}`")
        transcript_lines.append(f"- Orchestrator launched: {record.get('launched', False)}")
        transcript_lines.append("")

    (logs_dir / "compose-transcript.md").write_text(
        "\n".join(transcript_lines).strip() + "\n",
        encoding="utf-8",
    )
    (logs_dir / "compose-status-snapshot.json").write_text(
        json.dumps(status, indent=2),
        encoding="utf-8",
    )

    if final_output_rel:
        final_output_path = run_dir / final_output_rel
        if final_output_path.exists():
            (logs_dir / "compose-final-output-snapshot.md").write_text(
                final_output_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )


def wait_for_run_completion(run_dir: Path, timeout_s: int = RUN_WAIT_TIMEOUT_S) -> dict[str, Any] | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = read_status(run_dir)
        if status and status.get("state") in ("completed", "failed"):
            return status
        time.sleep(5)
    return read_status(run_dir)


def verify_topology(scenario: Scenario, plan: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    pattern = plan.get("pattern")
    nodes = plan.get("nodes", [])
    cycles = plan.get("cycles", [])
    root_count = sum(1 for node in nodes if not node.get("depends_on"))

    if pattern != scenario.expected_pattern:
        issues.append(f"Pattern mismatch: expected {scenario.expected_pattern}, found {pattern}")

    if scenario.expected_pattern == "chained-iteration":
        if len(nodes) != 1:
            issues.append(f"Expected 1 node, found {len(nodes)}")
        if not any(c.get("type") == "self-loop" for c in cycles):
            issues.append("Expected a self-loop cycle")
    elif scenario.expected_pattern in ("rag-grounded", "rubric-based"):
        if len(nodes) != 2:
            issues.append(f"Expected 2 nodes, found {len(nodes)}")
        if not any(c.get("type") == "bipartite" for c in cycles):
            issues.append("Expected a bipartite cycle")
    elif scenario.expected_pattern == "dissensus-integration":
        if len(nodes) < 4:
            issues.append(f"Expected at least 4 nodes, found {len(nodes)}")
        if root_count < 3:
            issues.append(f"Expected at least 3 panelist roots, found {root_count}")
    elif scenario.expected_pattern in ("consensus-panel", "debate-panel"):
        if len(nodes) != 9:
            issues.append(f"Expected 9 nodes, found {len(nodes)}")
        if root_count != 4:
            issues.append(f"Expected 4 root panelists, found {root_count}")
    elif scenario.expected_pattern == "parallel-decomposition":
        if root_count != 1:
            issues.append(f"Expected 1 decomposer root, found {root_count}")
        if len(nodes) < 2:
            issues.append(f"Expected at least 2 nodes, found {len(nodes)}")

    return issues


def verify_rag_prompt_isolation(agents_dir: Path) -> list[str]:
    issues: list[str] = []
    generator_path = agents_dir / "plan-generator.md"
    evaluator_path = agents_dir / "toc-evaluator.md"

    if not generator_path.exists():
        return ["Missing plan-generator.md for rag-grounded verification"]
    if not evaluator_path.exists():
        return ["Missing toc-evaluator.md for rag-grounded verification"]

    try:
        generator_text = generator_path.read_text(encoding="utf-8").lower()
        evaluator_text = evaluator_path.read_text(encoding="utf-8").lower()
    except OSError as e:
        return [f"Failed to read rag-grounded agent files: {e}"]

    for snippet in RAG_GENERATOR_FORBIDDEN_SNIPPETS:
        if snippet in generator_text:
            issues.append(
                f"rag-grounded generator prompt leaks hidden context via '{snippet}'"
            )
            break

    if re.search(r"\btoc\b", generator_text):
        issues.append("rag-grounded generator prompt leaks hidden context via 'ToC'")

    if "h:/toc" not in evaluator_text and "h:\\toc" not in evaluator_text:
        issues.append("rag-grounded evaluator prompt is missing the H:/ToC corpus path")

    if (
        "d:/dropbox/repository/llms/reference/toc" in evaluator_text
        or "d:\\dropbox\\repository\\llms\\reference\\toc" in evaluator_text
    ):
        issues.append("rag-grounded evaluator prompt still points at the old D:/.../Reference/ToC path")

    return issues


def verify_run_artifacts(
    scenario: Scenario,
    run_dir: Path,
    *,
    require_screenshots: bool,
    status_override: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    config_path = run_dir / "config.json"
    plan_path = run_dir / "execution_plan.json"
    agents_dir = run_dir / "agents"
    screenshots_dir = run_dir / "screenshots"

    if not config_path.exists():
        issues.append("Missing config.json")
    if not plan_path.exists():
        issues.append("Missing execution_plan.json")
        return issues
    if not agents_dir.exists() or not list(agents_dir.glob("*.md")):
        issues.append("No agent markdown files were generated")

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        issues.append(f"Failed to parse execution_plan.json: {e}")
        return issues

    issues.extend(verify_topology(scenario, plan))
    if scenario.name == "rag-grounded":
        issues.extend(verify_rag_prompt_isolation(agents_dir))

    status = status_override or read_status(run_dir)
    if status is None:
        issues.append("Missing logs/status.json")
    elif status.get("state") != "completed":
        issues.append(f"Run status is not completed: {status.get('state')}")
    elif scenario.min_bipartite_rounds > 0:
        cycle_states = status.get("cycles", {})
        bipartite_cycles = [
            (cycle_name, cycle_data)
            for cycle_name, cycle_data in cycle_states.items()
            if cycle_data.get("type") == "bipartite"
        ]
        if not bipartite_cycles:
            issues.append(
                f"Expected a bipartite cycle state for {scenario.name}, but none were recorded in status.json"
            )
        for cycle_name, cycle_data in bipartite_cycles:
            observed_rounds = int(cycle_data.get("current_round") or 0)
            if observed_rounds < scenario.min_bipartite_rounds:
                issues.append(
                    f"{scenario.name} did not naturally validate: cycle {cycle_name} ended after "
                    f"{observed_rounds} round(s), need at least {scenario.min_bipartite_rounds}"
                )

    for node in plan.get("nodes", []):
        for rel_output in node.get("outputs", []):
            output_path = run_dir / rel_output
            if not output_path.exists():
                issues.append(f"Missing declared output: {rel_output}")
                continue
            if output_path.is_file() and output_path.stat().st_size == 0:
                issues.append(f"Empty declared output: {rel_output}")

    final_output = plan.get("final_output")
    if final_output and not (run_dir / final_output).exists():
        issues.append(f"Missing final output: {final_output}")

    if require_screenshots and (not screenshots_dir.exists() or not list(screenshots_dir.glob("*.png"))):
        issues.append("No screenshots were captured during rerun")

    return issues


def run_scenario(
    scenario: Scenario,
    *,
    max_turns: int,
    rerun_for_screenshots: bool,
    mock_user_provider: str,
    chatgpt_model: str,
) -> tuple[Path | None, list[str]]:
    if scenario.seed_setup:
        scenario.seed_setup()

    session_id = str(uuid.uuid4())
    turn = run_compose_turn(
        scenario.initial_command,
        session_id=session_id,
        resume=False,
    )
    session_id = turn.session_id or session_id
    run_dir = turn.run_dir
    turn_records: list[dict[str, Any]] = [{
        "user": scenario.initial_command,
        "assistant": turn.final_text,
        "launched": turn.orchestrator_launched,
        "run_dir": str(turn.run_dir) if turn.run_dir else None,
    }]

    for turn_index in range(1, max_turns + 1):
        if turn.run_dir:
            run_dir = turn.run_dir

        if turn.orchestrator_launched:
            break

        if turn_index == max_turns:
            raise RuntimeError(
                f"{scenario.name}: compose never launched the orchestrator within {max_turns} turns"
            )
        if not turn.final_text.strip():
            raise RuntimeError(f"{scenario.name}: compose turn ended without a textual question/response")

        reply = generate_mock_user_reply(
            turn.final_text,
            scenario,
            provider=mock_user_provider,
            chatgpt_model=chatgpt_model,
        )
        turn = run_compose_turn(
            reply,
            session_id=session_id,
            resume=True,
        )
        session_id = turn.session_id or session_id
        turn_records.append({
            "user": reply,
            "assistant": turn.final_text,
            "launched": turn.orchestrator_launched,
            "run_dir": str(turn.run_dir) if turn.run_dir else None,
        })

    if run_dir is None:
        raise RuntimeError(f"{scenario.name}: could not determine the generated run directory")

    status = wait_for_run_completion(run_dir)
    if status is None:
        raise RuntimeError(f"{scenario.name}: status.json never appeared in {run_dir}")

    issues: list[str] = []
    if status.get("state") != "completed":
        issues.append(f"Compose-launched run did not complete successfully: {status.get('state')}")

    plan_path = run_dir / "execution_plan.json"
    final_output_rel = None
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            final_output_rel = plan.get("final_output")
        except (OSError, json.JSONDecodeError):
            final_output_rel = None
    _write_compose_artifacts(run_dir, turn_records, status, final_output_rel)

    if rerun_for_screenshots:
        run_run_dir(run_dir, pattern_label=scenario.expected_pattern)

    issues.extend(
        verify_run_artifacts(
            scenario,
            run_dir,
            require_screenshots=rerun_for_screenshots,
            status_override=status,
        )
    )
    return run_dir, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end compose harness for multi-agent-graph")
    parser.add_argument("scenario", help="Pattern/scenario to run, or 'all'")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=MAX_TURNS_DEFAULT,
        help=f"Maximum compose clarification turns before failing (default: {MAX_TURNS_DEFAULT})",
    )
    parser.add_argument(
        "--rerun-for-screenshots",
        action="store_true",
        help="After the native compose-launched run finishes, start a second deterministic rerun for screenshots",
    )
    parser.add_argument(
        "--mock-user-provider",
        choices=("haiku", "chatgpt"),
        default="haiku",
        help="Which model/backend should simulate the user during compose (default: haiku)",
    )
    parser.add_argument(
        "--chatgpt-model",
        default=CHATGPT_MOCK_USER_MODEL,
        help=f"OpenAI model to use when --mock-user-provider=chatgpt (default: {CHATGPT_MOCK_USER_MODEL})",
    )
    args = parser.parse_args()

    if args.scenario == "all":
        scenario_names = list(SCENARIOS)
    else:
        if args.scenario not in SCENARIOS:
            parser.error(f"Unknown scenario '{args.scenario}'. Choices: all, {', '.join(SCENARIOS)}")
        scenario_names = [args.scenario]

    print("=" * 60)
    print("multi-agent-graph - End-to-End Compose Test")
    print("=" * 60)
    print(f"Mock user provider: {args.mock_user_provider}")

    failures = 0
    for scenario_name in scenario_names:
        scenario = SCENARIOS[scenario_name]
        print(f"\n--- {scenario.name} ---")
        try:
            run_dir, issues = run_scenario(
                scenario,
                max_turns=args.max_turns,
                rerun_for_screenshots=args.rerun_for_screenshots,
                mock_user_provider=args.mock_user_provider,
                chatgpt_model=args.chatgpt_model,
            )
        except Exception as e:
            failures += 1
            print(f"[FAIL] {scenario.name}: {e}")
            continue

        if issues:
            failures += 1
            print(f"[FAIL] {scenario.name}")
            print(f"  Run dir: {run_dir}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK] {scenario.name}")
            print(f"  Run dir: {run_dir}")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if failures:
        print(f"{failures} scenario(s) failed")
        sys.exit(1)
    print("All scenarios passed")


if __name__ == "__main__":
    main()
