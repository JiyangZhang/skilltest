from __future__ import annotations

import subprocess as _sp
from pathlib import Path

from rich.console import Console

from skilltest.docker_runner import run_claude_code_in_docker
from skilltest.grader import grade_expectation
from skilltest.loader import load_tests
from skilltest.models import (
    CanonicalSkill,
    ExecutionMetrics,
    ExpectationResult,
    GradingReport,
    OracleType,
    SetupStep,
    TestResult,
)
from skilltest.parser import parse_skill
from skilltest.run_bundle import prepare_run_directory, read_run_bundle, write_manifest

console = Console()


def run_suite(
    skill_path: Path,
    tests_path: Path | None,
    output_dir: Path = Path("results"),
    docker_image: str | None = None,
    run_workspace_base: Path | None = None,
    agent_model: str | None = None,
    debug: bool = False,
    judge_model: str | None = None,
) -> GradingReport:

    skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
    skill = parse_skill(skill_path)
    test_suite = load_tests(skill_path, tests_path)

    needs_agent_judge = any(
        e.oracle == OracleType.AGENT_JUDGE
        for t in test_suite.tests
        for e in t.expectations
    )

    if test_suite.skill_name != skill.name:
        raise ValueError(
            f"skill_name in tests.json ('{test_suite.skill_name}') does not match "
            f"SKILL.md name ('{skill.name}'). Fix one to match the other."
        )

    runs_base = run_workspace_base or (output_dir / "agent-runs")
    runs_base.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]SkillTest[/bold] — [cyan]{skill.name}[/cyan]")
    console.print("Executor : [bold]docker[/bold]")
    if needs_agent_judge:
        model_label = judge_model or "claude (default)"
        console.print(f"Judge    : [bold]agent-judge[/bold] — {model_label}")
    console.print(f"Tests    : {len(test_suite.tests)} test cases")
    console.print()

    all_expectation_results: list[ExpectationResult] = []
    test_results: list[TestResult] = []
    all_metrics: list[ExecutionMetrics] = []

    for test_case in test_suite.tests:
        console.rule(f"Test {test_case.id}")

        if test_case.setup:
            _execute_steps(test_case.setup, skill_dir, run_dir=runs_base / f"test-{test_case.id}")

        try:
            output, metrics = _run_test_docker(
                skill_dir=skill_dir,
                skill=skill,
                test_case=test_case,
                runs_base=runs_base,
                docker_image=docker_image,
                constraints=test_case.constraints,
                agent_model=agent_model,
                debug=debug,
            )

            all_metrics.append(metrics)
            preview = output[:100].replace("\n", " ") if output else "(empty)"
            console.print(f"  Output: {preview}{'...' if len(output) > 100 else ''}")

            run_dir_for_grade = runs_base / f"test-{test_case.id}"
            artifacts_dir = None
            try:
                bundle = read_run_bundle(run_dir_for_grade)
                artifacts_dir = bundle.artifacts_dir
            except FileNotFoundError:
                artifacts_dir = run_dir_for_grade / "output" / "artifacts"

            exp_results: list[ExpectationResult] = []
            for exp in test_case.expectations:
                result = grade_expectation(
                    exp,
                    output,
                    test_case.prompt,
                    test_case.id,
                    skill_path=skill_dir,
                    artifacts_dir=artifacts_dir,
                    run_dir=run_dir_for_grade,
                    judge_model=judge_model,
                    debug=debug,
                )
                exp_results.append(result)
                all_expectation_results.append(result)
                icon = "✓" if result.passed else "✗"
                oracle_tag = f"[{result.oracle_used.value}]"
                console.print(f"  {icon} {oracle_tag} {exp.text[:70]}")
                if not result.passed:
                    console.print(f"       → {result.evidence}")
        finally:
            if test_case.cleanup:
                _execute_steps(test_case.cleanup, skill_dir, run_dir=runs_base / f"test-{test_case.id}")

        n_passed = sum(1 for r in exp_results if r.passed)
        n_total = len(exp_results)
        pass_rate = n_passed / n_total if n_total > 0 else 0.0
        test_results.append(
            TestResult(
                test_id=test_case.id,
                prompt=test_case.prompt,
                output=output,
                expectation_results=exp_results,
                metrics=metrics,
                pass_rate=pass_rate,
            )
        )

    total_passed = sum(1 for r in all_expectation_results if r.passed)
    total = len(all_expectation_results)
    overall_pass_rate = round(total_passed / total, 3) if total > 0 else 0.0

    timing: dict = {
        "agent": "docker",
        "docker_image": docker_image or "default",
    }

    report = GradingReport(
        expectations=all_expectation_results,
        summary={
            "passed": total_passed,
            "failed": total - total_passed,
            "total": total,
            "pass_rate": overall_pass_rate,
        },
        execution_metrics={
            "total_duration_seconds": sum(m.duration_seconds for m in all_metrics),
            "total_tokens": sum(m.tokens for m in all_metrics),
        },
        timing=timing,
        test_results=test_results,
    )

    _print_summary(report, console)
    return report


def _run_test_docker(
    skill_dir: Path,
    skill: CanonicalSkill,
    test_case,
    runs_base: Path,
    docker_image: str | None,
    constraints=None,
    agent_model: str | None = None,
    debug: bool = False,
) -> tuple[str, ExecutionMetrics]:
    import time

    run_root = runs_base / f"test-{test_case.id}"
    input_src = None
    if test_case.input_dir:
        input_src = skill_dir / test_case.input_dir

    prompt_text = _build_docker_task_prompt(skill, test_case.prompt)
    prepare_run_directory(run_root, prompt_text=prompt_text, input_src=input_src)

    console.print(f"  Running Docker agent (run dir: {run_root})...", end=" ")
    t0 = time.perf_counter()
    max_steps = constraints.max_steps if constraints else None
    timeout_seconds = constraints.timeout_seconds if constraints else None
    proc = run_claude_code_in_docker(
        run_root,
        skills_host_path=skill_dir.parent,
        docker_image=docker_image,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        agent_model=agent_model,
        debug=debug,
    )
    elapsed = time.perf_counter() - t0
    console.print(f"docker exit {proc.returncode} ({elapsed:.1f}s)")
    if proc.stderr:
        err_preview = proc.stderr[:500].replace("\n", " ")
        console.print(f"  [dim]docker stderr: {err_preview}[/dim]")

    write_manifest(
        run_root,
        test_id=test_case.id,
        exit_code=proc.returncode,
        docker_image=docker_image,
    )

    stdout_path = run_root / "output" / "stdout.txt"
    if not stdout_path.is_file():
        stdout_path.write_text(
            proc.stdout or "",
            encoding="utf-8",
        )
    try:
        bundle = read_run_bundle(run_root)
        text = bundle.stdout_text
    except FileNotFoundError:
        text = proc.stdout or ""

    metrics = ExecutionMetrics(
        output_chars=len(text),
        transcript_chars=len(test_case.prompt) + len(text),
        duration_seconds=round(elapsed, 3),
        errors_encountered=1 if proc.returncode != 0 else 0,
    )
    return text, metrics


def _execute_steps(
    steps: list[SetupStep],
    skill_dir: Path,
    run_dir: Path | None = None,
) -> list[str]:
    """Execute setup or cleanup steps; return a list of warning messages for any failures."""
    warnings: list[str] = []
    for step in steps:
        if step.shell:
            try:
                _sp.run(
                    step.shell,
                    shell=True,
                    cwd=skill_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except _sp.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()[:200]
                warnings.append(f"shell step failed ({step.shell!r}): {stderr}")
            except _sp.TimeoutExpired:
                warnings.append(f"shell step timed out after 60s: {step.shell!r}")
        elif step.file is not None:
            base = run_dir if run_dir is not None else skill_dir
            dest = base / step.file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(step.content or "", encoding="utf-8")
    return warnings


def _build_docker_task_prompt(skill: CanonicalSkill, user_prompt: str) -> str:
    """Augment the task so the agent writes the SkillTest run bundle layout."""
    return f"""{user_prompt}

---
## Required output for SkillTest (follow exactly)

Write a concise summary of your result to: `output/stdout.txt` (under the workspace root).
Place any files the task asks you to create under: `output/artifacts/`
Use paths relative to the workspace root (e.g. `output/stdout.txt`, `output/artifacts/...`).
Skill under test: **{skill.name}**
"""


def _print_summary(report: GradingReport, console: Console):
    pct = int(report.summary["pass_rate"] * 100)
    bar_len = 30
    filled = int(bar_len * report.summary["pass_rate"])
    bar = "█" * filled + "░" * (bar_len - filled)
    console.print(f"\n{'='*50}")
    console.print(f"  [{bar}] {pct}%")
    console.print(f"  Passed : {report.summary['passed']}/{report.summary['total']}")
    console.print(f"  Failed : {report.summary['failed']}/{report.summary['total']}")
    console.print(f"{'='*50}\n")
    for r in report.expectations:
        if not r.passed:
            console.print(f"  ✗ [Test {r.test_id}] {r.text}")
            console.print(f"    → {r.evidence}")
