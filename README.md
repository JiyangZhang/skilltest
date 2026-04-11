# SkillTest

A standalone testing framework for agent skills. Currently runs agents via **Claude Code**; support for additional agent runtimes is planned.

Agent skills are hard to verify. Write a `SKILL.md`, deploy it, and you're left hoping the model does what you intended. SkillTest changes that: **write tests alongside your skills, run them automatically, and know whether your skill works.** [Watch the demo video here.](https://youtu.be/dMv5o8ZCCBg)

---

## Why SkillTest

Most agent skills are tested informally, if at all. Developers prompt the model a few times, eyeball the output, and ship. Existing evaluation tools treat the skill definition and its tests as separate concerns — tests live in a different repo, a different tool, or not at all.

SkillTest is built around a different practice: **every skill ships with its tests**. When you write a skill, you write its tests. The tests live alongside the skill definition in the same directory:

```
my-skill/
├── SKILL.md          ← the skill definition
├── Dockerfile        ← execution environment (optional — for pinned dependencies)
└── tests/
    ├── tests.yaml    ← test cases and expectations
    └── pytests/      ← pre-written pytest checks on agent output (optional)
        ├── conftest.py
        └── test_output.py
```

SkillTest automates the full test cycle — loading the skill, invoking the agent via Docker to finish some task with the skill, grading the agent's output, and reporting results — so you get the same fast feedback loop for agent skills that you get for ordinary code.

Here is a test that tests the agent correctly counts the pdf page with the skill `pdf`:

```yaml
# tests/tests.yaml
skill_name: pdf  # the skill under test
tests:
  - name: page-count
    prompt: How many pages does input/guide.pdf have? Just tell me the number.
    input_dir: tests/input
    expectations:
      - text: Agent reports the correct page count (3)
        oracle: pytest
        pytest_path: tests/pytests/test_page_count.py
```

> **Agent runtime:** SkillTest currently runs agents using **Claude Code** inside Docker. Support for additional agent runtimes (Gemini CLI, OpenClaw) is on the roadmap.

---

## 📋 Requirements

- 🐍 **Python 3.11+**
- 🐳 **Docker** — required for `skilltest run`
- 🔑 **`ANTHROPIC_API_KEY`** — required for `agent-judge` expectations; `pytest` expectations work without it

---

## 🚀 Quickstart

This quickstart uses `skills/pdf-skills/` — a working skill included in the repo — so you can run a real test end-to-end in three steps.

### Step 1 — Install

```bash
git clone https://github.com/JiyangZhang/skilltest
cd skilltest
pip install -e .
```

### Step 2 — Build the Docker image

```bash
docker build -t skilltest-pdf:latest -f skills/pdf-skills/Dockerfile .
```

### Step 3 — Run the demo

```bash
export ANTHROPIC_API_KEY=sk-ant-...

cd skills/pdf-skills
skilltest run . --docker-image skilltest-pdf:latest --agent-model claude-haiku-4-5-20251001 --judge-model claude-haiku-4-5-20251001
```

SkillTest will spin up a Docker container per test case, run the Claude Code agent, grade each expectation, and write results to `skills/pdf-skills/skilltest-results/`:

```
skills/pdf-skills/
└── skilltest-results/
    ├── grading.json   ← machine-readable results
    ├── grading.xml    ← JUnit XML for CI
    └── report.html    ← HTML dashboard
```

Open the dashboard:

```bash
open skills/pdf-skills/skilltest-results/report.html
```

**Options:**

```bash
# Stream live agent traces (tool calls, file writes) for debugging
skilltest run . --debug

# Use a faster/cheaper model for the agent
skilltest run . --agent-model claude-haiku-4-5-20251001

# Use a specific model for agent-judge grading
skilltest run . --judge-model claude-haiku-4-5-20251001
```

---

## ⚙️ How it works

```
skilltest run <skill-dir>
  │
  ├─ for each test case in tests/tests.yaml:
  │    ├─ spin up Docker container (Claude Code agent)
  │    ├─ mount skill dir + input files read-only
  │    ├─ run agent against the test prompt
  │    ├─ capture output/stdout.txt and output/artifacts/
  │    └─ grade each expectation:
  │         ├─ pytest      → run pre-written pytest checks on the host
  │         └─ agent-judge → spin up a Docker container (Claude Code agent) to inspect output + files
  │
  └─ write skilltest-results/grading.json, grading.xml, report.html
```

The agent under test and the agent-judge both run **inside** Docker; only `pytest` grading runs on the host. The per-test workspace (`skilltest-results/agent-runs/test-N/`) is mounted into the container and remains on disk after the run for inspection.

---

## ✍️ Writing tests for your skill

This is the core of SkillTest. Tests live in `tests/tests.yaml` inside the skill directory and are the primary artifact you author. A test suite is a list of **test cases**. Each test case is one scenario you want to verify — a task the agent should handle, the input files it needs, and the criteria it must satisfy.

### Test cases and expectations

A **test case** sends a task prompt to the agent and runs it inside Docker. An **expectation** is a single graded criterion that the agent's output must satisfy. One test case can have multiple expectations — each is graded independently and contributes to the overall pass rate.

Think of it this way:
- **Test case** = the scenario or task ("merge these two PDFs")
- **Expectation** = one thing that must be true about the result ("the merged file has 3 pages", "the content is correct")

```
test case 2: merge PDFs
  ├── expectation A: merged.pdf exists and has 3 pages  → graded by pytest      → PASS ✓
  └── expectation B: content from both files is present → graded by agent-judge → PASS ✓
```

### Writing `tests.yaml`

Create `tests/tests.yaml` in your skill directory. Here is the complete file for `skills/pdf-skills/`:

```yaml
# skills/pdf-skills/tests/tests.yaml
skill_name: pdf
schema_version: 1

tests:
  - name: page-count
    prompt: |
      How many pages does input/guide.pdf have?
      Just tell me the number.
    input_dir: tests/input          # contents mounted at input/ inside the container
    expectations:
      - text: Output mentions the correct page count (3)
        oracle: pytest
        pytest_path: tests/pytests/test_page_count.py

  - name: merge-pdfs
    prompt: |
      Merge input/chapter1.pdf and input/chapter2.pdf into a single file.
      Save the result as output/artifacts/merged.pdf.
    input_dir: tests/input
    expectations:
      - text: merged.pdf exists in artifacts and contains all 3 pages
        oracle: pytest
        pytest_path: tests/pytests/test_merge.py
      - text: Two PDFs are merged successfully
        oracle: agent-judge
        rubric:
          - merged.pdf exists and includes content from both source PDFs
```

Test case 1 has one expectation graded by a pytest file. Test case 2 has two expectations: one deterministic check (file exists, correct page count) and one judgment check (content quality). The agent runs once per test case; all expectations are graded against the same output.

### Test case fields

| Field | Description |
|---|---|
| `name` | String. Unique within the suite (e.g. `page-count`, `merge-pdfs`). |
| `prompt` | The task sent to the agent verbatim. |
| `input_dir` | Path relative to skill root; its contents are copied to `input/` inside the container. |
| `expectations` | List of graded criteria — see below. |
| `setup` / `cleanup` | Shell commands or file writes to run on the host before/after the agent. |
| `constraints` | `{timeout_seconds, max_steps}` — hard limits on the agent run. |

### Expectations and oracles

Each expectation has a `text` (what you're checking) and an `oracle` (how it's graded). Two oracles are supported:

| Oracle | How it grades | When to use |
|---|---|---|
| `pytest` | Runs a pre-written Python test file. Pass = exit code 0. | Deterministic checks: file exists, page count, JSON structure, required keywords. |
| `agent-judge` | A Claude Code agent runs in Docker with the artifacts directory mounted read-only. It reads the expectation text, the agent's output, and can inspect artifact files. | Judgment calls: content accuracy, completeness, tone. |

If `oracle` is omitted it defaults to `agent-judge`.

```yaml
expectations:
  # deterministic — you write the assertion
  - text: merged.pdf exists in artifacts and has exactly 3 pages
    oracle: pytest
    pytest_path: tests/pytests/test_merge.py   # omit to run all tests/pytests/

  # judgment — Claude evaluates it; rubric adds explicit criteria
  - text: The merged PDF preserves content from both source files
    oracle: agent-judge
    rubric:
      - Chapter 1 content appears on page 1
      - Chapter 2 content appears on pages 2–3
```

`agent-judge` requires `ANTHROPIC_API_KEY` and Docker. `pytest` needs neither.

---

## Writing pytest checks

Use `pytest` expectations for anything you can express as a deterministic assertion — file existence, page counts, JSON structure, required keywords. Use `agent-judge` for judgment calls — accuracy, tone, content quality.

> 💡 **Not sure how to write pytest checks?** Use the [`skills/write-skilltest-pytests`](skills/write-skilltest-pytests/SKILL.md) skill — it knows the SkillTest conventions and will generate the files for you.

SkillTest injects these environment variables into your pytest subprocess:

| Variable | Contents |
|---|---|
| `SKILLTEST_OUTPUT` | The agent's full stdout as a string |
| `SKILLTEST_ARTIFACTS_DIR` | Absolute path to `output/artifacts/` |
| `SKILLTEST_RUN_DIR` | Absolute path to the per-test run bundle root |
| `SKILLTEST_SKILL_DIR` | Absolute path to the skill root |

**`tests/pytests/conftest.py`** (scaffolded by `skilltest init`):

```python
import os
import pytest

@pytest.fixture
def agent_output() -> str:
    return os.environ["SKILLTEST_OUTPUT"]
```

**Example — check a file was created with the right page count** (`skills/pdf-skills/tests/pytests/test_merge.py`):

```python
import os
from pathlib import Path
from pypdf import PdfReader

def test_merged_pdf_exists():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    assert (artifacts / "merged.pdf").exists()

def test_merged_pdf_has_three_pages():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    reader = PdfReader(str(artifacts / "merged.pdf"))
    assert len(reader.pages) == 3
```

**Example — check the agent's text output** (`skills/pdf-skills/tests/pytests/test_page_count.py`):

```python
import os, re

def test_output_mentions_page_count(agent_output):
    assert re.search(r"\b3\b|three", agent_output, re.IGNORECASE), \
        f"Expected agent to report 3 pages, got:\n{agent_output[:300]}"
```

**Debugging pytest checks locally** without running Docker:

```bash
cd skills/pdf-skills
export SKILLTEST_OUTPUT="The guide has 3 pages."
export SKILLTEST_ARTIFACTS_DIR=$(pwd)/skilltest-results/agent-runs/test-1/output/artifacts
export SKILLTEST_SKILL_DIR=$(pwd)
python -m pytest tests/pytests/test_page_count.py -v
```

Point `pytest_path` at a specific file when different test cases need different checks:

```yaml
- text: Page count is correct
  oracle: pytest
  pytest_path: tests/pytests/test_page_count.py
```

Omit `pytest_path` to run the entire `tests/pytests/` directory.

---

## 📊 Output

Results are written to `skilltest-results/` inside the skill directory by default, regardless of where you invoke the command:

```bash
skilltest run skills/pdf-skills
# → writes to skills/pdf-skills/skilltest-results/
```

Add `skilltest-results/` to your skill's `.gitignore`.

| File | Description |
|---|---|
| `grading.json` | Per-expectation results: `test_id`, `text`, `passed`, `evidence`, `oracle_used`, `duration_ms`. |
| `grading.xml` | JUnit XML for the same results (CI dashboards, GitHub Actions test reporter). |
| `report.html` | Self-contained HTML dashboard — pass rate, per-test cards with prompt and agent output, oracle badges, failure evidence. Supports light/dark mode. |
| `agent-runs/test-N/` | Full per-test workspace: `prompt.txt`, `input/`, `output/stdout.txt`, `output/artifacts/`, `output/manifest.json`. |

Regenerate `report.html` from a previous run at any time:

```bash
skilltest report skilltest-results/grading.json
```

---

## 🛠️ Commands

### `skilltest run`

```bash
skilltest run <skill-dir> [options]
```

| Option | Default | Purpose |
|---|---|---|
| `--output DIR` | `<skill-dir>/skilltest-results/` | Where to write results. |
| `--agent-model NAME` | image default | Claude model for the agent inside Docker. |
| `--judge-model NAME` | Claude default | Claude model for `agent-judge` grading. |
| `--docker-image NAME` | `skilltest-claude:latest` | Docker image to use (or `SKILLTEST_DOCKER_IMAGE` env). |
| `--run-workspace DIR` | `<output>/agent-runs` | Host directory for per-test run bundles. |
| `--min-pass-rate FLOAT` | `0.0` | Exit non-zero if pass rate falls below this (CI gate). |
| `--debug` | off | Stream agent and judge output live; adds `--verbose` to the agent. |
| `--tests PATH` | `<skill>/tests/tests.yaml` | Alternate tests file. |

### `skilltest report`

```bash
skilltest report <grading.json> [--output DIR]
```

Generates `report.html` from a `grading.json` file. When `agent-runs/` exists alongside the grading file, the report is automatically enriched with the original prompt and agent output per test card.

### `skilltest init`

```bash
skilltest init <skill-name>
```

Scaffolds a new skill directory with `SKILL.md`, `tests/tests.yaml`, and starter pytest files:

```
my-skill/
├── SKILL.md
└── tests/
    ├── tests.yaml
    └── pytests/
        ├── conftest.py
        └── test_output.py
```

---

## 🐳 Docker

### Base image

`docker/Dockerfile.claude` is the only image you need to build. It contains the Claude Code CLI and Python:

```bash
docker build -t skilltest-claude:latest -f docker/Dockerfile.claude docker/
```

The agent installs any skill-specific packages it needs at runtime via `pip install` — no skill-level Dockerfile required. This is consistent with how Claude Code works in practice: the agent is capable of setting up its own environment.

### Bringing your own image

For production or CI use cases where you want deterministic, fast runs without runtime installs, you can provide a custom image. Place a `Dockerfile` alongside `SKILL.md` in the skill directory:

```dockerfile
# my-skill/Dockerfile
FROM skilltest-claude:latest
RUN pip3 install --break-system-packages pandas openpyxl
```

Build it and pass it to `skilltest run`:

```bash
docker build -t my-skill:latest my-skill/
skilltest run ./my-skill --docker-image my-skill:latest
```

This is an opt-in. The default (`skilltest-claude:latest`) works for any skill without extra setup.


