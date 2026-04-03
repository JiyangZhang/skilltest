import yaml
import typer
from pathlib import Path
from rich.console import Console
from typing import Annotated, Optional

app = typer.Typer(
    name="skilltest",
    help="A portable, framework-agnostic testing framework for agent skills.",
    add_completion=False,
)
console = Console()

_DEFAULT_OUTPUT = Path("skilltest-results")


@app.command()
def run(
    skill: Annotated[Path, typer.Argument(help="Path to skill directory")],
    tests: Annotated[Optional[Path], typer.Option(help="Path to tests.json")] = None,
    output: Annotated[Path, typer.Option(help="Output directory")] = _DEFAULT_OUTPUT,
    min_pass_rate: Annotated[float, typer.Option(help="Minimum pass rate (CI gate)")] = 0.0,
    docker_image: Annotated[Optional[str], typer.Option(help="Override Docker image (default: env SKILLTEST_DOCKER_IMAGE or skilltest-claude:latest)")] = None,
    run_workspace: Annotated[Optional[Path], typer.Option(help="Host directory for per-test run bundles (default: <output>/agent-runs)")] = None,
    agent_model: Annotated[Optional[str], typer.Option(help="Claude model for the agent inside Docker (e.g. claude-haiku-4-5-20251001)")] = None,
    debug: Annotated[bool, typer.Option(help="Stream agent and judge output live; adds --verbose to the agent")] = False,
    judge_model: Annotated[Optional[str], typer.Option(help="Claude model for agent-judge oracle (e.g. claude-haiku-4-5-20251001); requires 'claude' CLI on host PATH")] = None,
):
    """Run the test suite for a skill (Docker agent required)."""
    from skilltest.parser import parse_skill
    from skilltest.runner import run_suite
    from skilltest.writer import write_grading, write_html_report

    skill_name = parse_skill(skill).name
    report = run_suite(
        skill_path=skill,
        tests_path=tests,
        output_dir=output,
        docker_image=docker_image,
        run_workspace_base=run_workspace,
        agent_model=agent_model,
        debug=debug,
        judge_model=judge_model,
    )
    json_path, xml_path = write_grading(report, output, skill_name=skill_name)
    html_path = write_html_report(report, output, skill_name=skill_name)
    console.print(f"\nResults written to [cyan]{output}/[/cyan]")
    console.print(f"  JSON  : {json_path.name}")
    console.print(f"  JUnit : {xml_path.name}")
    console.print(f"  Report: {html_path.name}")

    if min_pass_rate > 0 and report.summary["pass_rate"] < min_pass_rate:
        console.print(
            f"[red]FAIL: pass rate {report.summary['pass_rate']:.2f} "
            f"< required {min_pass_rate:.2f}[/red]"
        )
        raise typer.Exit(1)


@app.command()
def report(
    grading: Annotated[Path, typer.Argument(help="Path to grading.json")],
    output: Annotated[Optional[Path], typer.Option(help="Output directory (default: same directory as grading.json)")] = None,
):
    """Generate an HTML dashboard from a grading.json file."""
    from skilltest.writer import write_html_report_from_json

    if not grading.is_file():
        console.print(f"[red]File not found: {grading}[/red]")
        raise typer.Exit(1)

    out_dir = output or grading.parent
    html_path = write_html_report_from_json(grading, out_dir)
    console.print(f"Report written to [cyan]{html_path}[/cyan]")


@app.command()
def diff(
    before: Annotated[Path, typer.Argument(help="Path to first grading.json")],
    after: Annotated[Path, typer.Argument(help="Path to second grading.json")],
    output: Annotated[Path, typer.Option(help="Output directory")] = _DEFAULT_OUTPUT,
):
    """Compare two grading.json files and show regressions and fixes."""
    from skilltest.diff import diff_reports
    from skilltest.writer import write_diff

    report = diff_reports(before, after)

    if report.regressions:
        console.print(f"\n[red]Regressions ({len(report.regressions)}):[/red]")
        for r in report.regressions:
            console.print(f"  ✗ [Test {r.test_id}] {r.text}")
    if report.fixes:
        console.print(f"\n[green]Fixes ({len(report.fixes)}):[/green]")
        for f in report.fixes:
            console.print(f"  ✓ [Test {f.test_id}] {f.text}")

    console.print(f"\nStable passes: {report.stable_passes}")
    console.print(f"Stable fails:  {report.stable_fails}")
    net = report.net_change
    color = "green" if net > 0 else "red" if net < 0 else "white"
    console.print(f"Net change:    [{color}]{'+' if net > 0 else ''}{net}[/{color}]")

    path = write_diff(report, output)
    console.print(f"\nDiff written to [cyan]{path}[/cyan]")


@app.command()
def coverage(
    skill: Annotated[Path, typer.Argument(help="Path to skill directory")],
    tests: Annotated[Optional[Path], typer.Option(help="Path to tests.json")] = None,
    output: Annotated[Path, typer.Option()] = _DEFAULT_OUTPUT,
    provider: Annotated[str, typer.Option()] = "anthropic",
    model: Annotated[Optional[str], typer.Option()] = None,
    runs: Annotated[int, typer.Option(help="Runs per (section, test) pair")] = 2,
    threshold: Annotated[float, typer.Option(help="Minimum section coverage (CI gate)")] = 0.0,
    confirm: Annotated[bool, typer.Option(help="Skip cost confirmation prompt")] = False,
):
    """Run ablation-based coverage analysis on the skill body."""
    from skilltest.providers import make_provider
    from skilltest.loader import load_tests
    from skilltest.parser import parse_skill
    from skilltest.coverage import run_coverage
    from skilltest.writer import write_coverage

    p = make_provider(f"{provider}:{model}" if model else provider)
    skill_obj = parse_skill(skill)
    test_suite = load_tests(skill, tests)

    n_sections = len(skill_obj.sections)
    n_tests = sum(1 for t in test_suite.tests if t.expectations)
    est_calls = n_sections * n_tests * runs * 2
    console.print(
        f"\nCoverage analysis: {n_sections} sections × {n_tests} tests (with expectations) × {runs} runs"
    )
    console.print(f"Estimated executor calls: ~{est_calls}")

    if est_calls > 50 and not confirm:
        typer.confirm(f"This will make ~{est_calls} API calls. Continue?", abort=True)

    report = run_coverage(skill, test_suite, p, n_runs=runs)
    json_path, md_path = write_coverage(report, output)

    console.print(f"\nOverall coverage: {int(report.overall_coverage * 100)}%")
    for s in report.sections:
        icon = "✓" if s.verdict in ("WELL_COVERED", "COVERED") else "⚠" if s.verdict == "WEAKLY_COVERED" else "✗"
        path_str = " > ".join(s.heading_path)
        console.print(f"  {icon} {path_str}: {s.coverage_score:.2f} ({s.verdict})")
    console.print(f"\nReport: [cyan]{md_path}[/cyan]")

    if threshold > 0:
        failing = [s for s in report.sections if s.coverage_score < threshold]
        if failing:
            console.print(f"[red]FAIL: {len(failing)} section(s) below threshold {threshold}[/red]")
            raise typer.Exit(1)


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Skill name (kebab-case)")],
    output: Annotated[Path, typer.Option(help="Directory to create skill in")] = Path("."),
):
    """Scaffold a new skill directory with SKILL.md and tests/tests.json."""
    skill_dir = output / name
    tests_dir = skill_dir / "tests"
    pytests_dir = tests_dir / "pytests"
    pytests_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: >\n  Describe what this skill does and when to trigger it.\n---\n\n"
        f"# {name.replace('-', ' ').title()}\n\n## What this skill does\n\n[Describe the skill]\n\n"
        f"## Steps\n\n1. Step one\n2. Step two\n\n## Output format\n\n[Describe expected output]\n",
        encoding="utf-8",
    )
    (tests_dir / "tests.yaml").write_text(
        yaml.dump({
            "schema_version": 1,
            "skill_name": name,
            "tests": [{
                "id": 1,
                "prompt": "Example prompt that should trigger this skill",
                "expectations": [
                    {"text": "Pre-written pytest checks under tests/pytests pass", "oracle": "pytest"},
                    {"text": "The output addresses the user's request", "oracle": "agent-judge"},
                ],
            }]
        }, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (pytests_dir / "conftest.py").write_text(
        'import os\n'
        'import json\n'
        'import pytest\n'
        '\n'
        '\n'
        '@pytest.fixture\n'
        'def agent_output() -> str:\n'
        '    """Raw text output from the agent under test."""\n'
        '    return os.environ["SKILLTEST_OUTPUT"]\n'
        '\n'
        '\n'
        '@pytest.fixture\n'
        'def agent_output_json() -> dict:\n'
        '    """Agent output parsed as JSON. Fails if output is not valid JSON."""\n'
        '    return json.loads(os.environ["SKILLTEST_OUTPUT"])\n',
        encoding="utf-8",
    )
    (pytests_dir / "test_output.py").write_text(
        'import os\n'
        'import json\n'
        '\n'
        '\n'
        'def test_output_is_not_empty():\n'
        '    output = os.environ["SKILLTEST_OUTPUT"]\n'
        '    assert output.strip(), "Agent produced no output"\n'
        '\n'
        '\n'
        '# Example: uncomment and adapt for JSON-returning skills\n'
        '# def test_output_is_valid_json():\n'
        '#     output = os.environ["SKILLTEST_OUTPUT"]\n'
        '#     data = json.loads(output)\n'
        '#     assert isinstance(data, dict)\n',
        encoding="utf-8",
    )
    console.print(f"\n[green]Scaffold created at {skill_dir}[/green]")
    console.print(f"  Edit [cyan]{skill_dir}/SKILL.md[/cyan] to define your skill")
    console.print(f"  Edit [cyan]{tests_dir}/tests.json[/cyan] to add test cases")
    console.print(f"  Edit [cyan]{pytests_dir}/test_output.py[/cyan] to add pytest checks on agent output")
    console.print(f"\nRun the test suite (Docker agent required):")
    console.print(f"  [bold]skilltest run {skill_dir}[/bold]")


if __name__ == "__main__":
    app()
