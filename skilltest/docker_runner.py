"""Run the SkillTest Docker image with a prepared run directory."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Container working directory layout (must match docker/entrypoint.sh)
CONTAINER_WORKSPACE = "/workspace"


def default_image() -> str:
    return os.environ.get("SKILLTEST_DOCKER_IMAGE", "skilltest-claude:latest")


def run_claude_code_in_docker(
    run_root: Path,
    *,
    skills_host_path: Path,
    docker_image: str | None = None,
    extra_env: dict[str, str] | None = None,
    max_steps: int | None = None,
    timeout_seconds: float | None = None,
    agent_model: str | None = None,
    debug: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``docker run`` with run_root and skills tree mounted.

    ``skills_host_path`` should be the parent directory that contains the skill
    under test (mounted read-only at ``/workspace/skills``).

    When ``debug=True``, docker output streams live to the terminal and
    ``--verbose`` is added to the claude invocation so tool calls are visible.
    The run bundle (stdout.txt, artifacts/) is still written by the container
    via ``tee``, so grading works normally.
    """
    if shutil.which("docker") is None:
        raise RuntimeError(
            "Docker is not installed or not on PATH. Install Docker to run skilltest."
        )

    image = docker_image or default_image()
    run_root = run_root.resolve()
    skills_host_path = skills_host_path.resolve()

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{run_root}:{CONTAINER_WORKSPACE}",
        "-v",
        f"{skills_host_path}:{CONTAINER_WORKSPACE}/skills:ro",
    ]
    # Run as the host user so bind-mounted workspace dirs are writable and
    # Claude Code's --dangerously-skip-permissions works (it refuses to run as root).
    cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_SUBAGENT"):
        val = os.environ.get(key)
        if val:
            cmd.extend(["-e", f"{key}={val}"])
    # HOME is intentionally not forwarded from the host — the image sets
    # ENV HOME=/home/agent which is writable by any uid at runtime.
    cmd.extend(["-e", f"SKILLTEST_DOCKER_IMAGE={image}"])

    if agent_model is not None:
        cmd.extend(["-e", f"CLAUDE_CODE_MODEL={agent_model}"])

    # Build CLAUDE_CODE_ARGS: --max-turns and/or --verbose
    claude_extra: list[str] = []
    if max_steps is not None:
        claude_extra.extend(["--max-turns", str(max_steps)])
    if debug:
        claude_extra.append("--verbose")
    if claude_extra:
        cmd.extend(["-e", f"CLAUDE_CODE_ARGS={' '.join(claude_extra)}"])

    cmd.append(image)

    docker_timeout = timeout_seconds if timeout_seconds is not None else 7200

    if debug:
        # Stream output live — stdout.txt is still written inside container via tee
        return subprocess.run(
            cmd,
            env=env,
            timeout=docker_timeout,
        )

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=docker_timeout,
    )
