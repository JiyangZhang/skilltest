from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skilltest.docker_runner import run_claude_code_in_docker


def test_run_claude_code_raises_when_docker_missing():
    with patch("skilltest.docker_runner.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Docker"):
            run_claude_code_in_docker(Path("/tmp/run"), skills_host_path=Path("/skills"))


def test_run_claude_code_invokes_docker():
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ""
    proc.stderr = ""
    with patch("skilltest.docker_runner.shutil.which", return_value="/usr/bin/docker"), \
         patch("skilltest.docker_runner.subprocess.run", return_value=proc) as run:
        run_claude_code_in_docker(
            Path("/host/run"),
            skills_host_path=Path("/host/parent"),
            docker_image="skilltest:test",
        )
    assert run.called
    args = run.call_args[0][0]
    assert args[0] == "docker"
    assert any("skilltest:test" in str(a) for a in args)
