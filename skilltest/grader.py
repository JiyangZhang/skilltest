from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# Artifacts are mounted here inside the judge container (read-only).
_CONTAINER_ARTIFACTS = "/artifacts"

from skilltest.models import (
    Expectation,
    ExpectationResult,
    OracleType,
)


AGENT_JUDGE_PROMPT = """You are evaluating the output of an AI agent against a specific expectation.

The agent was given this task:
<prompt>
{prompt}
</prompt>

The agent produced this output:
<output>
{output}
</output>

{artifacts_note}

Evaluate this expectation:
<expectation>{expectation}</expectation>

{rubric_block}

Instructions:
- Be strict. Only pass if the expectation is clearly and unambiguously met.
- If artifact files are listed above, you may read them to verify the expectation.
- Respond with ONLY a single JSON object on one line — no prose before or after:
  {{"passed": true, "evidence": "one sentence explaining your decision"}}"""


def _docker_image() -> str:
    return os.environ.get("SKILLTEST_DOCKER_IMAGE", "skilltest-claude:latest")


def _run_judge_in_docker(
    judge_prompt: str,
    artifacts_dir: Path | None,
    judge_model: str | None,
    debug: bool = False,
) -> str:
    """Run the claude judge inside an isolated Docker container. Returns raw stdout."""
    import sys

    cmd = [
        "docker", "run", "--rm",
        "--entrypoint", "claude",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/home/agent",
    ]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

    if artifacts_dir is not None and artifacts_dir.is_dir():
        cmd.extend(["-v", f"{artifacts_dir.resolve()}:{_CONTAINER_ARTIFACTS}:ro"])

    cmd.append(_docker_image())
    cmd.extend(["-p", judge_prompt, "--dangerously-skip-permissions"])
    if judge_model:
        cmd.extend(["--model", judge_model])

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if debug:
            print(line, end="", flush=True, file=sys.stderr)
        lines.append(line)
    proc.wait()
    return "".join(lines).strip()


def agent_judge(
    expectation_text: str,
    output: str,
    prompt: str,
    artifacts_dir: Path | None = None,
    run_dir: Path | None = None,
    rubric: list[str] | None = None,
    judge_model: str | None = None,
    debug: bool = False,
) -> tuple[bool, str]:
    """Run a Claude Code agent inside Docker to grade an expectation.

    The judge runs in an isolated container with the artifacts directory mounted
    read-only at /artifacts, preventing prompt-injected output from affecting the host.
    """
    if shutil.which("docker") is None:
        return False, (
            "agent-judge requires Docker on the host PATH. "
            "Install Docker and ensure ANTHROPIC_API_KEY is set."
        )

    # Build artifacts note — reference the container-side path so the judge can read files
    if artifacts_dir is not None and artifacts_dir.is_dir():
        files = sorted(p.relative_to(artifacts_dir) for p in artifacts_dir.rglob("*") if p.is_file())
        if files:
            file_list = "\n".join(f"  - {f}" for f in files)
            artifacts_note = (
                f"Artifact files produced by the agent are at: {_CONTAINER_ARTIFACTS}\n"
                f"Files present:\n{file_list}\n"
                f"You may read these files to verify the expectation."
            )
        else:
            artifacts_note = "The agent produced no artifact files."
    else:
        artifacts_note = "No artifact directory available."

    rubric_block = ""
    if rubric:
        criteria = "\n".join(f"  - {c}" for c in rubric)
        rubric_block = f"Use this rubric to guide your evaluation:\n{criteria}"

    judge_prompt = AGENT_JUDGE_PROMPT.format(
        prompt=prompt,
        output=output[:3000],
        expectation=expectation_text,
        artifacts_note=artifacts_note,
        rubric_block=rubric_block,
    )

    try:
        raw = _run_judge_in_docker(judge_prompt, artifacts_dir, judge_model, debug=debug)
    except subprocess.TimeoutExpired:
        return False, "agent-judge timed out after 120s"

    # Extract the JSON object from the agent's response
    raw = re.sub(r"^```[a-z]*\n?|```$", "", raw, flags=re.MULTILINE).strip()
    # The agent may emit reasoning before the JSON — find the last {...} block
    match = re.search(r'\{[^{}]*"passed"[^{}]*\}', raw, re.DOTALL)
    if match:
        raw = match.group(0)
    try:
        parsed = json.loads(raw)
        return bool(parsed.get("passed", False)), str(parsed.get("evidence", ""))
    except json.JSONDecodeError:
        return False, f"agent-judge returned unparseable response: {raw[:200]}"


def grade_expectation(
    expectation: Expectation,
    output: str,
    prompt: str,
    test_id: int,
    skill_path: Path | None = None,
    artifacts_dir: Path | None = None,
    run_dir: Path | None = None,
    judge_model: str | None = None,
    debug: bool = False,
) -> ExpectationResult:
    t0 = time.perf_counter()
    oracle_used = expectation.oracle
    passed, evidence = False, ""

    if expectation.oracle == OracleType.PYTEST:
        from skilltest.pytest_runner import run_pytest
        skill_dir: Path | None = None
        if expectation.pytest_path is None:
            if skill_path is None:
                return ExpectationResult(
                    test_id=test_id, text=expectation.text, passed=False,
                    evidence="pytest oracle requires skill_path; none provided",
                    oracle_used=oracle_used,
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                )
            skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
            resolved = skill_dir / "tests" / "pytests"
        else:
            if skill_path is not None:
                skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
                resolved = skill_dir / expectation.pytest_path
            else:
                resolved = Path(expectation.pytest_path)
        passed, evidence = run_pytest(
            resolved,
            output,
            skill_dir=skill_dir,
            artifacts_dir=artifacts_dir,
            run_dir=run_dir,
        )

    elif expectation.oracle == OracleType.AGENT_JUDGE:
        passed, evidence = agent_judge(
            expectation.text, output, prompt,
            artifacts_dir=artifacts_dir,
            run_dir=run_dir,
            rubric=expectation.rubric or None,
            judge_model=judge_model,
            debug=debug,
        )

    else:
        return ExpectationResult(
            test_id=test_id,
            text=expectation.text,
            passed=False,
            evidence=f"Unsupported oracle: {expectation.oracle!r}",
            oracle_used=oracle_used,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    return ExpectationResult(
        test_id=test_id,
        text=expectation.text,
        passed=passed,
        evidence=evidence,
        oracle_used=oracle_used,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
