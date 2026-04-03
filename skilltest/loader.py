import yaml
from pathlib import Path
from skilltest.models import TestSuite, TestCase, Expectation, OracleType, SetupStep, TestConstraints

def _parse_oracle(raw: str | None) -> OracleType:
    if raw is None:
        return OracleType.AGENT_JUDGE
    key = raw.strip().lower()
    try:
        return OracleType(key)
    except ValueError as exc:
        raise ValueError(
            f"Unknown oracle {raw!r}. Use 'agent-judge' or 'pytest'."
        ) from exc


def load_tests(skill_path: Path, tests_path: Path | None = None) -> TestSuite:
    """Load and validate tests/tests.yaml from the skill directory."""
    if tests_path is None:
        skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
        tests_path = skill_dir / "tests" / "tests.yaml"
    else:
        skill_dir = skill_path if skill_path.is_dir() else skill_path.parent

    if not tests_path.exists():
        raise FileNotFoundError(f"tests.yaml not found at {tests_path}")

    raw = yaml.safe_load(tests_path.read_text(encoding="utf-8"))

    if "skill_name" not in raw:
        raise ValueError("tests.json must contain 'skill_name'")

    tests_list = raw.get("tests")
    if tests_list is None or not isinstance(tests_list, list):
        raise ValueError("tests.json must contain a 'tests' list")

    schema_version = int(raw.get("schema_version", 1))

    test_cases = []
    for item in tests_list:
        expectations = []
        for e in item.get("expectations", []):
            if isinstance(e, dict):
                oracle_raw = e.get("oracle", "llm-judge")
                expectations.append(Expectation(
                    text=e["text"],
                    oracle=_parse_oracle(oracle_raw),
                    pytest_path=e.get("pytest_path"),
                    rubric=e.get("rubric", []),
                ))

        task_file = item.get("task_file")
        prompt_inline = item.get("prompt", "") or ""
        if task_file:
            tf = skill_dir / task_file
            if not tf.is_file():
                raise ValueError(f"task_file not found for test {item.get('id')}: {tf}")
            text_from_file = tf.read_text(encoding="utf-8")
            if prompt_inline.strip():
                merged_prompt = text_from_file.strip() + "\n\n" + prompt_inline.strip()
            else:
                merged_prompt = text_from_file
        else:
            if not str(prompt_inline).strip():
                raise ValueError(
                    f"test id {item.get('id')}: provide non-empty 'prompt' and/or 'task_file'"
                )
            merged_prompt = prompt_inline

        input_dir = item.get("input_dir")
        if input_dir:
            idp = skill_dir / input_dir
            if not idp.is_dir():
                raise ValueError(f"input_dir is not a directory for test {item.get('id')}: {idp}")

        setup = _parse_setup_steps(item.get("setup", []))
        cleanup = _parse_setup_steps(item.get("cleanup", []))

        constraints_raw = item.get("constraints")
        constraints = TestConstraints(**constraints_raw) if constraints_raw else None

        test_cases.append(TestCase(
            id=item["id"],
            prompt=merged_prompt,
            expected_output=item.get("expected_output", ""),
            files=item.get("files", []),
            expectations=expectations,
            input_dir=input_dir,
            task_file=task_file,
            setup=setup,
            cleanup=cleanup,
            constraints=constraints,
        ))

    return TestSuite(
        skill_name=raw["skill_name"],
        tests=test_cases,
        schema_version=schema_version,
    )


def _parse_setup_steps(raw: list) -> list[SetupStep]:
    steps = []
    for item in raw:
        if isinstance(item, str):
            steps.append(SetupStep(shell=item))
        elif isinstance(item, dict):
            steps.append(SetupStep(
                shell=item.get("shell"),
                file=item.get("file"),
                content=item.get("content"),
            ))
    return steps


