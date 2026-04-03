from pathlib import Path
from unittest.mock import patch

from skilltest.grader import grade_expectation
from skilltest.models import Expectation, OracleType


def test_pytest_oracle_without_skill_path_returns_failure():
    exp = Expectation(text="passes pytest", oracle=OracleType.PYTEST)
    result = grade_expectation(exp, "output", "prompt", 1, skill_path=None)
    assert result.passed is False
    assert "skill_path" in result.evidence


def test_pytest_oracle_runs_written_tests(tmp_path):
    pytests = tmp_path / "tests" / "pytests"
    pytests.mkdir(parents=True)
    (pytests / "test_x.py").write_text(
        "import os\n"
        "def test_out():\n"
        "    assert os.environ['SKILLTEST_OUTPUT'] == 'ok'\n",
        encoding="utf-8",
    )
    exp = Expectation(text="pytest checks", oracle=OracleType.PYTEST)
    result = grade_expectation(exp, "ok", "prompt", 1, skill_path=tmp_path)
    assert result.passed is True
    assert result.oracle_used == OracleType.PYTEST


def test_agent_judge_without_docker_on_path_returns_failure():
    exp = Expectation(text="output is correct", oracle=OracleType.AGENT_JUDGE)
    with patch("skilltest.grader.shutil.which", return_value=None):
        result = grade_expectation(exp, "output", "prompt", 1)
    assert result.passed is False
    assert "docker" in result.evidence.lower()
