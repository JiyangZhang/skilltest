import yaml
import pytest
import tempfile
from pathlib import Path
from skilltest.loader import load_tests
from skilltest.models import OracleType


def write_tests(tmp_dir: Path, data: dict) -> Path:
    tests_dir = tmp_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "tests.yaml").write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return tmp_dir


def test_valid_tests_loads():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        skill_path = write_tests(tmp, {
            "skill_name": "my-skill",
            "tests": [{
                "id": 1,
                "prompt": "test prompt",
                "expectations": [{"text": "output is valid", "oracle": "agent-judge"}]
            }]
        })
        suite = load_tests(skill_path)
        assert suite.skill_name == "my-skill"
        assert len(suite.tests) == 1
        assert suite.tests[0].id == 1


def test_missing_skill_name_raises():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        skill_path = write_tests(tmp, {
            "tests": [{"id": 1, "prompt": "test"}]
        })
        with pytest.raises(ValueError, match="skill_name"):
            load_tests(skill_path)


def test_dict_expectation_format():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        skill_path = write_tests(tmp, {
            "skill_name": "my-skill",
            "tests": [{
                "id": 1,
                "prompt": "test",
                "expectations": [{"text": "check this", "oracle": "agent-judge"}]
            }]
        })
        suite = load_tests(skill_path)
        assert suite.tests[0].expectations[0].oracle == OracleType.AGENT_JUDGE


def test_missing_tests_file_raises():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FileNotFoundError):
            load_tests(Path(tmp))


def test_task_file_and_prompt_merge(tmp_path):
    skill_path = tmp_path
    task = skill_path / "tests" / "task.md"
    task.parent.mkdir(parents=True)
    task.write_text("From file\n", encoding="utf-8")
    (skill_path / "tests" / "tests.yaml").write_text(
        "skill_name: x\n"
        "tests:\n"
        "  - id: 1\n"
        "    task_file: tests/task.md\n"
        "    prompt: Extra\n"
        "    expectations: []\n",
        encoding="utf-8",
    )
    (skill_path / "SKILL.md").write_text(
        "---\nname: x\ndescription: d\n---\nbody",
        encoding="utf-8",
    )
    suite = load_tests(skill_path)
    assert "From file" in suite.tests[0].prompt
    assert "Extra" in suite.tests[0].prompt


def test_input_dir_must_exist(tmp_path):
    skill_path = tmp_path
    (skill_path / "tests").mkdir(parents=True)
    (skill_path / "tests" / "tests.yaml").write_text(
        "skill_name: x\n"
        "tests:\n"
        "  - id: 1\n"
        "    prompt: p\n"
        "    input_dir: tests/missing\n"
        "    expectations: []\n",
        encoding="utf-8",
    )
    (skill_path / "SKILL.md").write_text(
        "---\nname: x\ndescription: d\n---\nbody",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="input_dir"):
        load_tests(skill_path)


# ── Setup / cleanup / constraints ────────────────────────────────────────────

def test_setup_shell_string_is_parsed(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "setup": ["echo hello"],
            "expectations": [],
        }],
    })
    suite = load_tests(tmp_path)
    assert len(suite.tests[0].setup) == 1
    assert suite.tests[0].setup[0].shell == "echo hello"
    assert suite.tests[0].setup[0].file is None


def test_setup_file_dict_is_parsed(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "setup": [{"file": "input/data.txt", "content": "test data"}],
            "expectations": [],
        }],
    })
    suite = load_tests(tmp_path)
    step = suite.tests[0].setup[0]
    assert step.file == "input/data.txt"
    assert step.content == "test data"
    assert step.shell is None


def test_cleanup_steps_are_parsed(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "cleanup": [{"shell": "rm -f /tmp/test-artifact"}],
            "expectations": [],
        }],
    })
    suite = load_tests(tmp_path)
    assert suite.tests[0].cleanup[0].shell == "rm -f /tmp/test-artifact"


def test_constraints_are_parsed(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "constraints": {"timeout_seconds": 30, "max_steps": 5},
            "expectations": [],
        }],
    })
    suite = load_tests(tmp_path)
    c = suite.tests[0].constraints
    assert c is not None
    assert c.timeout_seconds == 30
    assert c.max_steps == 5


def test_constraints_partial_fields(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "constraints": {"timeout_seconds": 60},
            "expectations": [],
        }],
    })
    suite = load_tests(tmp_path)
    c = suite.tests[0].constraints
    assert c.timeout_seconds == 60
    assert c.max_steps is None


def test_no_constraints_field_is_none(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{"id": 1, "prompt": "p", "expectations": []}],
    })
    suite = load_tests(tmp_path)
    assert suite.tests[0].constraints is None


def test_unknown_oracle_rejected(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "expectations": [{"text": "check", "oracle": "deterministic"}],
        }],
    })
    with pytest.raises(ValueError, match="Unknown oracle"):
        load_tests(tmp_path)


def test_rubric_is_parsed(tmp_path):
    write_tests(tmp_path, {
        "skill_name": "my-skill",
        "tests": [{
            "id": 1,
            "prompt": "p",
            "expectations": [{
                "text": "response quality",
                "oracle": "agent-judge",
                "rubric": ["Is factually accurate", "Is concise"],
            }],
        }],
    })
    suite = load_tests(tmp_path)
    exp = suite.tests[0].expectations[0]
    assert exp.rubric == ["Is factually accurate", "Is concise"]
