import os
import pytest


@pytest.fixture
def agent_output() -> str:
    """Raw text output from the agent under test."""
    return os.environ["SKILLTEST_OUTPUT"]
