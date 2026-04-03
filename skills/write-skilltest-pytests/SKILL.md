---
name: write-skilltest-pytests
description: Use this skill when you need to write pytest files for a skill which will be executed with skilltest. It explains what SkillTest pytests are, where they live, and how to write them.
---

# Writing SkillTest Pytest Files

## What SkillTest pytests are

SkillTest grades each test case expectation with an *oracle*. The `pytest` oracle runs a Python file you write to check the agent's output deterministically — file existence, page counts, JSON structure, keyword matches, etc. Use `pytest` for anything you can express as a concrete assertion. Use `agent-judge` for judgment calls (content quality, tone, completeness).

## File system structure

Pytest files live inside the skill directory:

```
my-skill/
├── SKILL.md
└── tests/
    ├── tests.yaml
    └── pytests/
        ├── conftest.py          ← fixtures shared across all test files
        ├── test_case1.py        ← checks for test case 1
        └── test_case2.py        ← checks for test case 2
```

A test case in `tests.yaml` points to its pytest file via `pytest_path`:

```yaml
expectations:
  - text: merged.pdf exists and has 3 pages
    oracle: pytest
    pytest_path: tests/pytests/test_merge.py
```

Omit `pytest_path` to run the entire `tests/pytests/` directory for that expectation.

## Environment variables

SkillTest injects these into every pytest subprocess:

| Variable | Value |
|---|---|
| `SKILLTEST_OUTPUT` | Agent's full stdout as a string |
| `SKILLTEST_ARTIFACTS_DIR` | Absolute path to `output/artifacts/` |
| `SKILLTEST_RUN_DIR` | Absolute path to the per-test run workspace root |
| `SKILLTEST_SKILL_DIR` | Absolute path to the skill root |

## conftest.py

Always include this. It exposes `SKILLTEST_OUTPUT` as a pytest fixture:

```python
import os
import pytest


@pytest.fixture
def agent_output() -> str:
    """Raw text output from the agent under test."""
    return os.environ["SKILLTEST_OUTPUT"]
```

## Patterns

### Check the agent reported a value in text output

```python
import os
import re


def test_output_mentions_count(agent_output):
    assert re.search(r"\b3\b|three", agent_output, re.IGNORECASE), \
        f"Expected agent to report 3, got:\n{agent_output[:300]}"
```

### Check a file was created in artifacts

```python
import os
from pathlib import Path


def test_output_file_exists():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    path = artifacts / "result.csv"
    assert path.exists(), (
        f"Expected result.csv in {artifacts}. "
        f"Found: {list(artifacts.iterdir()) if artifacts.exists() else 'directory missing'}"
    )
```

### Check a JSON artifact

```python
import os
import json
from pathlib import Path


def test_json_structure():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    data = json.loads((artifacts / "result.json").read_text())
    assert "items" in data, "Expected 'items' key in result.json"
    assert len(data["items"]) == 3, f"Expected 3 items, got {len(data['items'])}"
```

## Good practices

- Use `pytest.skip()` when a prerequisite file is missing, so downstream checks skip rather than fail with a confusing error.
- Include context in assertion messages: expected value, actual value, relevant file path.
- One assertion per test function — easier to see exactly what failed.
- Import heavy libraries (pypdf, pandas) inside the test function or after an existence check, so a missing artifact gives a clean `skip` rather than an `ImportError`.
