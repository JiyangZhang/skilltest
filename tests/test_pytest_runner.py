import tempfile
from pathlib import Path

from skilltest.pytest_runner import run_pytest


def _write_test(tmp: Path, name: str, content: str) -> Path:
    f = tmp / name
    f.write_text(content, encoding="utf-8")
    return f


def test_passing_test_returns_true():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_pass.py",
            'import os\n'
            'def test_output_present():\n'
            '    assert os.environ.get("SKILLTEST_OUTPUT") == "hello"\n'
        )
        passed, evidence = run_pytest(test_file, "hello")
        assert passed is True


def test_failing_test_returns_false():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_fail.py",
            'def test_always_fails():\n'
            '    assert False, "this always fails"\n'
        )
        passed, evidence = run_pytest(test_file, "some output")
        assert passed is False


def test_evidence_contains_failure_message():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_msg.py",
            'def test_with_message():\n'
            '    assert 1 == 2, "one is not two"\n'
        )
        passed, evidence = run_pytest(test_file, "output")
        assert passed is False
        assert "one is not two" in evidence


def test_missing_path_returns_failure():
    passed, evidence = run_pytest(Path("/nonexistent/path/test_x.py"), "output")
    assert passed is False
    assert "not found" in evidence


def test_skilltest_output_env_var_is_injected():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_env.py",
            'import os\n'
            'def test_env_value():\n'
            '    assert os.environ["SKILLTEST_OUTPUT"] == "injected content"\n'
        )
        passed, _ = run_pytest(test_file, "injected content")
        assert passed is True


def test_skilltest_output_file_env_var_is_injected():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_file_env.py",
            'import os\n'
            'def test_file_readable():\n'
            '    path = os.environ["SKILLTEST_OUTPUT_FILE"]\n'
            '    content = open(path, encoding="utf-8").read()\n'
            '    assert content == "file content"\n'
        )
        passed, _ = run_pytest(test_file, "file content")
        assert passed is True


def test_can_run_entire_directory():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_test(tmp, "test_a.py",
            'def test_one(): assert 1 + 1 == 2\n'
        )
        _write_test(tmp, "test_b.py",
            'def test_two(): assert "x" in "xyz"\n'
        )
        passed, _ = run_pytest(tmp, "anything")
        assert passed is True


def test_one_failing_test_in_dir_fails_suite():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_test(tmp, "test_good.py", 'def test_ok(): assert True\n')
        _write_test(tmp, "test_bad.py", 'def test_nope(): assert False\n')
        passed, _ = run_pytest(tmp, "anything")
        assert passed is False


def test_conftest_fixture_is_accessible():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_test(tmp, "conftest.py",
            'import os, pytest\n'
            '@pytest.fixture\n'
            'def agent_output():\n'
            '    return os.environ["SKILLTEST_OUTPUT"]\n'
        )
        _write_test(tmp, "test_fixture.py",
            'def test_uses_fixture(agent_output):\n'
            '    assert agent_output == "fixture value"\n'
        )
        passed, _ = run_pytest(tmp, "fixture value")
        assert passed is True


def test_multiline_output_is_fully_injected():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = _write_test(Path(tmp), "test_multiline.py",
            'import os\n'
            'def test_newlines():\n'
            '    out = os.environ["SKILLTEST_OUTPUT"]\n'
            '    assert "line1" in out\n'
            '    assert "line2" in out\n'
        )
        passed, _ = run_pytest(test_file, "line1\nline2\nline3")
        assert passed is True
