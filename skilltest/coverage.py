from pathlib import Path
from skilltest.models import (
    CanonicalSkill, TestSuite, SkillSection,
    SectionCoverageResult, CoverageReport,
)
from skilltest.executor import run_task
from skilltest.grader import grade_expectation
from skilltest.providers.base import SkillTestProvider
from rich.console import Console

console = Console()


def ablate_section(skill: CanonicalSkill, section: SkillSection) -> str:
    body = skill.body
    return body[:section.char_start] + body[section.char_end:]


def grade_full(skill: CanonicalSkill, eval_case, provider, n_runs: int,
               skill_dir: Path | None = None) -> list[bool]:
    results = []
    for _ in range(n_runs):
        output, _ = run_task(skill, eval_case.prompt, provider)
        passed_all = all(
            grade_expectation(exp, output, eval_case.prompt, eval_case.id, provider, skill_dir).passed
            for exp in eval_case.expectations
        )
        results.append(passed_all)
    return results


def grade_ablated(skill: CanonicalSkill, section: SkillSection,
                  eval_case, provider, n_runs: int,
                  skill_dir: Path | None = None) -> list[bool]:
    ablated_body = ablate_section(skill, section)
    results = []
    for _ in range(n_runs):
        output, _ = run_task(skill, eval_case.prompt, provider,
                             skill_body_override=ablated_body)
        passed_all = all(
            grade_expectation(exp, output, eval_case.prompt, eval_case.id, provider, skill_dir).passed
            for exp in eval_case.expectations
        )
        results.append(passed_all)
    return results


def majority(bools: list[bool]) -> bool:
    return sum(bools) > len(bools) / 2


def run_coverage(
    skill_path,
    suite: TestSuite,
    provider: SkillTestProvider,
    n_runs: int = 2,
) -> CoverageReport:
    from skilltest.parser import parse_skill
    skill_dir = Path(skill_path) if Path(skill_path).is_dir() else Path(skill_path).parent
    skill = parse_skill(Path(skill_path))

    total_calls = 0
    section_results: list[SectionCoverageResult] = []

    for section in skill.sections:
        tests_covered = []
        tests_tested = []

        for test_case in suite.tests:
            if not test_case.expectations:
                continue

            full_outcomes = grade_full(skill, test_case, provider, n_runs, skill_dir)
            total_calls += n_runs
            stable_full = majority(full_outcomes)

            ablated_outcomes = grade_ablated(skill, section, test_case, provider, n_runs, skill_dir)
            total_calls += n_runs
            stable_ablated = majority(ablated_outcomes)

            tests_tested.append(test_case.id)
            if stable_full != stable_ablated:
                tests_covered.append(test_case.id)

        n_covered = len(tests_covered)
        n_tested = len(tests_tested)
        score = round(n_covered / n_tested, 2) if n_tested > 0 else 0.0

        if score == 0.0:
            verdict = "DEAD"
            rec = (
                f"Section '{' > '.join(section.heading_path)}' never affects output. "
                f"Remove it to reduce context token usage, or add tests that exercise it."
            )
        elif score < 0.34:
            verdict = "WEAKLY_COVERED"
            rec = f"Add more tests targeting '{' > '.join(section.heading_path)}'."
        elif score < 0.67:
            verdict = "COVERED"
            rec = ""
        else:
            verdict = "WELL_COVERED"
            rec = ""

        section_results.append(SectionCoverageResult(
            section_id=section.id,
            heading_path=section.heading_path,
            coverage_score=score,
            tests_covered=tests_covered,
            tests_tested=tests_tested,
            verdict=verdict,
            recommendation=rec,
        ))

    overall = round(
        sum(r.coverage_score for r in section_results) / len(section_results), 2
    ) if section_results else 0.0

    dead = [r.section_id for r in section_results if r.verdict == "DEAD"]

    return CoverageReport(
        skill_name=skill.name,
        overall_coverage=overall,
        sections=section_results,
        dead_sections=dead,
        executor_calls_made=total_calls,
    )
