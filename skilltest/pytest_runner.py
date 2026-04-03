from __future__ import annotations

import os
import sys
import subprocess
import tempfile
from pathlib import Path


def run_pytest(
    pytest_path: Path,
    output: str,
    *,
    skill_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    run_dir: Path | None = None,
) -> tuple[bool, str]:
    """
    Run pytest at pytest_path with the agent output injected via environment variables:
      SKILLTEST_OUTPUT      — the raw output string
      SKILLTEST_OUTPUT_FILE — path to a temp file containing the output
      SKILLTEST_ARTIFACTS_DIR — directory of files produced by the agent (optional)
      SKILLTEST_RUN_DIR — root of the materialized run bundle (optional)
      SKILLTEST_SKILL_DIR — skill root (directory containing SKILL.md); pytest cwd

    Returns (passed, evidence) where evidence is the captured pytest output.
    """
    pytest_path = pytest_path.resolve()
    if not pytest_path.exists():
        return False, f"pytest path not found: {pytest_path}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(output)
        tmp_path = f.name

    resolved_skill = skill_dir.resolve() if skill_dir is not None else None
    if resolved_skill is None and pytest_path.is_dir():
        try:
            if pytest_path.name == "pytests" and pytest_path.parent.name == "tests":
                resolved_skill = pytest_path.parent.parent
        except IndexError:
            resolved_skill = None
    if resolved_skill is not None and resolved_skill.is_dir():
        cwd = resolved_skill
    else:
        cwd = pytest_path.parent if pytest_path.is_file() else pytest_path
    cwd = cwd.resolve()

    env = os.environ.copy()
    env["SKILLTEST_OUTPUT"] = output
    env["SKILLTEST_OUTPUT_FILE"] = tmp_path
    if resolved_skill is not None and resolved_skill.is_dir():
        env["SKILLTEST_SKILL_DIR"] = str(resolved_skill.resolve())
    if artifacts_dir is not None:
        env["SKILLTEST_ARTIFACTS_DIR"] = str(artifacts_dir.resolve())
    if run_dir is not None:
        env["SKILLTEST_RUN_DIR"] = str(run_dir.resolve())

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(pytest_path), "--tb=short", "-q", "--no-header"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd),
        )
        passed = result.returncode == 0
        combined = (result.stdout + result.stderr).strip()
        if passed:
            evidence = combined or "All pytest tests passed"
        else:
            evidence = combined[:600] if combined else "pytest failed with no output"
        return passed, evidence
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
