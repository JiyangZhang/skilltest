# SkillUnit — Implementation Plan for Claude Code

> **This file is the single source of truth for implementing SkillUnit.**
> Read it fully before writing any code. Follow each phase in order.
> Do not skip ahead. When in doubt, re-read the relevant section.

---

## What you are building

**SkillUnit** is a standalone Python CLI package (`pip install skillunit`) that
brings JUnit-style testing discipline to agent skills. It reads Anthropic- or
OpenAI-format `SKILL.md` files plus an `evals/evals.json` test suite, runs the
skill against the Anthropic API, grades each expectation, and writes results in
the Anthropic-native `grading.json` schema.

Core commands when finished:
```
skillunit run      ./my-skill          # run full test suite
skillunit diff     v1.json v2.json     # regression diff between versions
skillunit coverage ./my-skill          # ablation-based coverage analysis
skillunit init     my-skill-name       # scaffold a new skill + evals
skillunit matrix   ./my-skill          # cross-model comparison
```

---

## Repository layout (create this exactly)

```
skillunit/                        ← root of the repo
├── AGENTS.md                     ← this file
├── README.md                     ← generated last
├── pyproject.toml
├── skillunit/                    ← Python package
│   ├── __init__.py
│   ├── cli.py                    ← Typer CLI entry point
│   ├── parser.py                 ← SKILL.md → CanonicalSkill
│   ├── loader.py                 ← evals.json → validated EvalSuite
│   ├── executor.py               ← run skill against provider API
│   ├── grader.py                 ← grade expectations (det + llm-judge)
│   ├── coverage.py               ← ablation-based coverage analysis
│   ├── mock.py                   ← tool call interception layer
│   ├── diff.py                   ← compare two grading.json files
│   ├── writer.py                 ← serialize all output formats
│   ├── models.py                 ← all Pydantic dataclasses
│   └── providers/
│       ├── __init__.py
│       ├── base.py               ← SkillUnitProvider protocol
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       └── local_provider.py     ← Ollama / LM Studio
├── tests/                        ← pytest unit tests
│   ├── test_parser.py
│   ├── test_grader.py
│   ├── test_diff.py
│   └── fixtures/
│       ├── anthropic_skill/
│       │   ├── SKILL.md
│       │   └── evals/evals.json
│       └── openai_skill/
│           ├── SKILL.md
│           └── evals/evals.json
└── example-skill/                ← working example for manual testing
    ├── SKILL.md
    └── evals/
        ├── evals.json
        └── mocks.json
```

---

## Phase 1 — Project scaffold and data models

### 1.1 `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "skillunit"
version = "0.1.0"
description = "A portable, framework-agnostic testing framework for agent skills"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "typer>=0.12.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "PyYAML>=6.0",
]

[project.scripts]
skillunit = "skillunit.cli:app"

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff"]
```

Install in editable mode immediately after creating: `pip install -e ".[dev]"`

### 1.2 `skillunit/models.py` — all dataclasses

Define every data model here. All other modules import from `models.py`.
No model definitions anywhere else.

```python
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Skill format ──────────────────────────────────────────────────────────────

class SkillFormat(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class SkillSection(BaseModel):
    """One removable section of a SKILL.md body (for coverage ablation)."""
    id: str                    # e.g. "rules.rule_1"
    heading_path: list[str]    # e.g. ["Rules", "Rule 1"]
    raw_text: str              # the exact markdown text of this section
    char_start: int            # offset in the full body string
    char_end: int


class CanonicalSkill(BaseModel):
    """Normalised representation of any skill format."""
    name: str
    description: str
    body: str                  # full SKILL.md body (after frontmatter)
    sections: list[SkillSection]
    source_format: SkillFormat
    source_path: str


# ── Evals ─────────────────────────────────────────────────────────────────────

class OracleType(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm-judge"
    AUTO = "auto"              # default: try deterministic, fall back to llm-judge


class Expectation(BaseModel):
    text: str
    oracle: OracleType = OracleType.AUTO


class EvalCase(BaseModel):
    id: int
    prompt: str
    expected_output: str = ""
    files: list[str] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)
    should_trigger: bool = True


class EvalSuite(BaseModel):
    skill_name: str
    evals: list[EvalCase]


# ── Mock definitions ──────────────────────────────────────────────────────────

class MockRule(BaseModel):
    match: dict[str, Any]      # key-value pairs to match against tool call args
    returns: Any               # fixture response to return


class MockDefinitions(BaseModel):
    """Contents of evals/mocks.json"""
    rules: dict[str, list[MockRule]] = Field(default_factory=dict)
    # keys are tool names: "read_file", "bash", "http_get", etc.


# ── Grading ───────────────────────────────────────────────────────────────────

class ExpectationResult(BaseModel):
    eval_id: int
    text: str
    passed: bool
    evidence: str
    oracle_used: OracleType
    duration_ms: float = 0.0


class ExecutionMetrics(BaseModel):
    tool_calls: dict[str, int] = Field(default_factory=dict)
    total_tool_calls: int = 0
    total_steps: int = 1
    errors_encountered: int = 0
    output_chars: int = 0
    transcript_chars: int = 0
    tokens: int = 0
    duration_seconds: float = 0.0


class EvalResult(BaseModel):
    eval_id: int
    prompt: str
    triggered: bool | None = None      # None = trigger test not run
    output: str
    expectation_results: list[ExpectationResult]
    metrics: ExecutionMetrics
    pass_rate: float = 0.0


class GradingReport(BaseModel):
    """Root object written to grading.json — Anthropic-native schema."""
    expectations: list[ExpectationResult]
    summary: dict[str, Any]            # passed, failed, total, pass_rate
    execution_metrics: dict[str, Any]
    timing: dict[str, Any]
    eval_results: list[EvalResult]     # extended: per-eval detail


# ── Coverage ──────────────────────────────────────────────────────────────────

class SectionCoverageResult(BaseModel):
    section_id: str
    heading_path: list[str]
    coverage_score: float              # 0.0 – 1.0
    evals_covered: list[int]           # eval IDs where ablation changed outcome
    evals_tested: list[int]
    verdict: str                       # "WELL_COVERED" | "COVERED" | "WEAKLY_COVERED" | "DEAD"
    recommendation: str


class CoverageReport(BaseModel):
    skill_name: str
    overall_coverage: float
    sections: list[SectionCoverageResult]
    dead_sections: list[str]           # section IDs with score == 0.0
    executor_calls_made: int


# ── Diff ─────────────────────────────────────────────────────────────────────

class ExpectationDiff(BaseModel):
    eval_id: int
    text: str
    before: bool
    after: bool
    change_type: str                   # "regression" | "fix" | "stable_pass" | "stable_fail"


class DiffReport(BaseModel):
    before_path: str
    after_path: str
    regressions: list[ExpectationDiff]
    fixes: list[ExpectationDiff]
    stable_passes: int
    stable_fails: int
    net_change: int                    # positive = more passing, negative = more failing
```

---

## Phase 2 — Parser (`skillunit/parser.py`)

**Responsibility:** Convert any SKILL.md file on disk into a `CanonicalSkill`.
Must handle both Anthropic and OpenAI formats. Must parse body sections for
coverage ablation.

### 2.1 Format detection

Both formats use YAML frontmatter delimited by `---`. Detection rules:

- **Anthropic format**: frontmatter has `name` and `description` fields.
  Body begins after the closing `---`. No structural difference in frontmatter.
- **OpenAI format**: identical frontmatter structure. SkillUnit treats them
  as the same format unless a future field distinguishes them.
- If no valid frontmatter is found, raise `SkillParseError` with a clear message.

### 2.2 Frontmatter parsing

```python
import re, yaml
from pathlib import Path
from skillunit.models import CanonicalSkill, SkillFormat, SkillSection, SkillParseError

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def parse_skill(skill_path: Path) -> CanonicalSkill:
    skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise SkillParseError(f"No SKILL.md found at {skill_file}")

    raw = skill_file.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise SkillParseError("SKILL.md must begin with YAML frontmatter (--- ... ---)")

    fm = yaml.safe_load(match.group(1))
    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name:
        raise SkillParseError("SKILL.md frontmatter must include 'name'")
    if not description:
        raise SkillParseError("SKILL.md frontmatter must include 'description'")

    body = raw[match.end():]
    sections = _parse_sections(body)

    return CanonicalSkill(
        name=name,
        description=description,
        body=body,
        sections=sections,
        source_format=SkillFormat.ANTHROPIC,
        source_path=str(skill_file),
    )
```

### 2.3 Section parsing (for coverage ablation)

Parse the body into independently removable sections. Granularity rules:

- **Level 1**: each `##` heading and everything under it until the next `##`
- **Level 2**: within a `##` block, each `###` heading is its own section
- **Level 3**: within `##` or `###` blocks that contain a numbered or bulleted
  list, each top-level list item is its own section

Implement as a recursive descent parser. Each section gets a stable `id` built
from its heading path joined with dots and slugified (e.g. `rules.rule_1`).

```python
def _parse_sections(body: str) -> list[SkillSection]:
    sections = []
    # Step 1: split by ## headings
    h2_blocks = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    offset = 0
    for block in h2_blocks:
        if not block.strip():
            offset += len(block)
            continue
        heading = re.match(r"^## (.+)$", block, re.MULTILINE)
        h2_name = heading.group(1).strip() if heading else "preamble"
        # Step 2: split each ## block by ### sub-headings
        h3_blocks = re.split(r"(?=^### )", block, flags=re.MULTILINE)
        h3_offset = offset
        for h3_block in h3_blocks:
            h3_heading = re.match(r"^### (.+)$", h3_block, re.MULTILINE)
            h3_name = h3_heading.group(1).strip() if h3_heading else None
            heading_path = [h2_name] + ([h3_name] if h3_name else [])
            # Step 3: split by list items within the block
            _extract_list_items(h3_block, heading_path, h3_offset, sections)
            h3_offset += len(h3_block)
        offset += len(block)
    return sections


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _extract_list_items(block: str, heading_path: list[str],
                        base_offset: int, sections: list[SkillSection]):
    """Extract numbered (1. 2. 3.) and bulleted (- * •) top-level list items."""
    item_re = re.compile(r"^(?:\d+\.|[-*•])\s+(.+?)(?=\n(?:\d+\.|[-*•])\s|\Z)",
                         re.MULTILINE | re.DOTALL)
    parent_id = ".".join(_slugify(h) for h in heading_path)
    for i, m in enumerate(item_re.finditer(block)):
        item_id = f"{parent_id}.item_{i+1}"
        sections.append(SkillSection(
            id=item_id,
            heading_path=heading_path + [f"item {i+1}"],
            raw_text=m.group(0),
            char_start=base_offset + m.start(),
            char_end=base_offset + m.end(),
        ))
    # If no list items found, add the entire block as one section
    if not item_re.search(block):
        section_id = ".".join(_slugify(h) for h in heading_path) or "body"
        sections.append(SkillSection(
            id=section_id,
            heading_path=heading_path,
            raw_text=block,
            char_start=base_offset,
            char_end=base_offset + len(block),
        ))
```

**Test this with `tests/test_parser.py` before moving on.** Verify:
- `parse_skill()` returns a `CanonicalSkill` with correct `name`, `description`, `body`
- `sections` is non-empty for any non-trivial skill body
- Each section's `char_start`/`char_end` correctly selects that text from `body`
- Missing frontmatter raises `SkillParseError`
- Missing `name` or `description` raises `SkillParseError`

---

## Phase 3 — Loader (`skillunit/loader.py`)

**Responsibility:** Read and validate `evals/evals.json`. Enforce the contract
that `skill_name` in the evals file matches the `name` in the parsed skill.

```python
import json
from pathlib import Path
from skillunit.models import EvalSuite, EvalCase, Expectation, OracleType

def load_evals(skill_path: Path, evals_path: Path | None = None) -> EvalSuite:
    if evals_path is None:
        skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
        evals_path = skill_dir / "evals" / "evals.json"

    if not evals_path.exists():
        raise FileNotFoundError(f"evals.json not found at {evals_path}")

    raw = json.loads(evals_path.read_text(encoding="utf-8"))

    if "skill_name" not in raw:
        raise ValueError("evals.json must contain 'skill_name'")
    if "evals" not in raw or not isinstance(raw["evals"], list):
        raise ValueError("evals.json must contain an 'evals' list")

    evals = []
    for item in raw["evals"]:
        expectations = []
        for e in item.get("expectations", []):
            if isinstance(e, str):
                # short form: just the text, oracle=AUTO
                expectations.append(Expectation(text=e))
            elif isinstance(e, dict):
                expectations.append(Expectation(
                    text=e["text"],
                    oracle=OracleType(e.get("oracle", "auto")),
                ))
        evals.append(EvalCase(
            id=item["id"],
            prompt=item["prompt"],
            expected_output=item.get("expected_output", ""),
            files=item.get("files", []),
            expectations=expectations,
            should_trigger=item.get("should_trigger", True),
        ))

    return EvalSuite(skill_name=raw["skill_name"], evals=evals)


def load_mocks(skill_path: Path) -> "MockDefinitions | None":
    skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
    mocks_path = skill_dir / "evals" / "mocks.json"
    if not mocks_path.exists():
        return None
    from skillunit.models import MockDefinitions, MockRule
    raw = json.loads(mocks_path.read_text(encoding="utf-8"))
    rules = {}
    for tool_name, rule_list in raw.items():
        rules[tool_name] = [MockRule(**r) for r in rule_list]
    return MockDefinitions(rules=rules)
```

---

## Phase 4 — Provider abstraction (`skillunit/providers/`)

### 4.1 `base.py` — protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SkillUnitProvider(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Send a completion request. Return the text response."""
        ...

    def model_id(self) -> str:
        """Return the model identifier string."""
        ...
```

### 4.2 `anthropic_provider.py`

```python
import anthropic
from skillunit.providers.base import SkillUnitProvider

class AnthropicProvider:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self._model = model
        self._client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text if response.content else ""

    def model_id(self) -> str:
        return self._model
```

### 4.3 `openai_provider.py`

```python
from openai import OpenAI
from skillunit.providers.base import SkillUnitProvider

class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o"):
        self._model = model
        self._client = OpenAI()              # reads OPENAI_API_KEY from env

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def model_id(self) -> str:
        return self._model
```

### 4.4 `local_provider.py`

```python
import httpx
from skillunit.providers.base import SkillUnitProvider

class LocalProvider:
    """Talks to any OpenAI-compatible local endpoint (Ollama, LM Studio)."""
    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        self._model = model
        self._base_url = base_url.rstrip("/")

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        r = httpx.post(f"{self._base_url}/v1/chat/completions", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def model_id(self) -> str:
        return f"local:{self._model}"
```

### 4.5 Provider factory

Add a factory function in `providers/__init__.py`:

```python
from skillunit.providers.anthropic_provider import AnthropicProvider
from skillunit.providers.openai_provider import OpenAIProvider
from skillunit.providers.local_provider import LocalProvider
from skillunit.providers.base import SkillUnitProvider

def make_provider(provider_str: str, model: str | None = None) -> SkillUnitProvider:
    """
    provider_str examples:
      "anthropic"                  → AnthropicProvider(default model)
      "anthropic:claude-haiku-4-5" → AnthropicProvider(claude-haiku-4-5)
      "openai"                     → OpenAIProvider(default model)
      "openai:gpt-4o-mini"         → OpenAIProvider(gpt-4o-mini)
      "local"                      → LocalProvider(default)
      "local:mistral"              → LocalProvider(mistral)
    """
    parts = provider_str.split(":", 1)
    name = parts[0].lower()
    model_override = parts[1] if len(parts) > 1 else model

    if name == "anthropic":
        return AnthropicProvider(model=model_override or "claude-sonnet-4-6")
    elif name == "openai":
        return OpenAIProvider(model=model_override or "gpt-4o")
    elif name == "local":
        return LocalProvider(model=model_override or "llama3")
    else:
        raise ValueError(f"Unknown provider: '{name}'. Choose: anthropic, openai, local")
```

---

## Phase 5 — Executor (`skillunit/executor.py`)

**Responsibility:** inject the skill body as a system prompt and call the
provider. Also run trigger probes. Respect mocks when provided.

### 5.1 System prompt construction

```python
def build_system_prompt(skill: CanonicalSkill) -> str:
    return (
        "You are Claude. The following skill is active for this session.\n"
        "Read it carefully and follow its instructions exactly when responding.\n\n"
        "=== SKILL: {name} ===\n"
        "{body}\n"
        "=== END SKILL ===\n\n"
        "Execute the user's request by following the skill's instructions."
    ).format(name=skill.name, body=skill.body)
```

### 5.2 Trigger probe

The trigger probe checks whether the model would invoke the skill given only its
`name` and `description` — not the full body. This mirrors how Claude Code's
skill selection actually works (description-first triggering).

```python
TRIGGER_PROBE_SYSTEM = """You are a skill routing agent. You have access to one skill:

Skill name: {name}
Skill description: {description}

Your ONLY job is to decide whether to invoke this skill for the user's request.
Respond with EXACTLY one word: YES or NO.
YES = this request is a good match for the skill and you would invoke it.
NO  = this request does not match the skill or you would not invoke it.
Do not explain. Do not add punctuation. Just YES or NO."""

def run_trigger_probe(
    skill: CanonicalSkill,
    prompt: str,
    provider: SkillUnitProvider,
) -> bool:
    system = TRIGGER_PROBE_SYSTEM.format(
        name=skill.name, description=skill.description
    )
    response = provider.complete(system=system, user=prompt, max_tokens=5)
    return response.strip().upper().startswith("YES")
```

### 5.3 Task execution

```python
import time
from skillunit.models import ExecutionMetrics

def run_task(
    skill: CanonicalSkill,
    prompt: str,
    provider: SkillUnitProvider,
    mock_definitions=None,        # MockDefinitions | None
    skill_body_override: str | None = None,  # for ablation
) -> tuple[str, ExecutionMetrics]:
    body = skill_body_override if skill_body_override is not None else skill.body
    system = build_system_prompt_from_body(skill.name, body)

    t0 = time.perf_counter()
    output = provider.complete(system=system, user=prompt, max_tokens=2048)
    elapsed = time.perf_counter() - t0

    metrics = ExecutionMetrics(
        output_chars=len(output),
        transcript_chars=len(prompt) + len(output),
        duration_seconds=round(elapsed, 3),
    )
    return output, metrics


def build_system_prompt_from_body(name: str, body: str) -> str:
    return (
        f"You are Claude. The following skill is active for this session.\n"
        f"Read it carefully and follow its instructions exactly when responding.\n\n"
        f"=== SKILL: {name} ===\n{body}\n=== END SKILL ===\n\n"
        f"Execute the user's request by following the skill's instructions."
    )
```

---

## Phase 6 — Grader (`skillunit/grader.py`)

This is the most important module. Implement it with care.

### 6.1 Deterministic rule classifier

The classifier reads the expectation text and tries to match it to a
deterministic rule. If it matches, grade without any API call.
If it doesn't match, return `None` so the caller falls back to the LLM judge.

```python
import json, re
from typing import Any

def try_deterministic(text: str, output: str) -> tuple[bool, str] | None:
    """
    Try to grade `text` against `output` deterministically.
    Returns (passed, evidence) if a rule matched, else None.
    """
    t = text.strip().lower()
    out_stripped = output.strip()

    # ── JSON validity ──────────────────────────────────────────────────────
    if "valid json" in t or "json object" in t or "json array" in t:
        try:
            parsed = json.loads(out_stripped)
            if "object" in t and not isinstance(parsed, dict):
                return False, f"Expected JSON object, got {type(parsed).__name__}"
            if "array" in t and not isinstance(parsed, list):
                return False, f"Expected JSON array, got {type(parsed).__name__}"
            return True, "Output is valid JSON"
        except json.JSONDecodeError as e:
            return False, f"JSON parse error: {e}"

    # ── Numeric equality: "X is exactly N" / "X equals N" ─────────────────
    exact_match = re.search(
        r'["\']?(\w+)["\']?\s+is\s+exactly\s+(\d+)', t
    ) or re.search(r'["\']?(\w+)["\']?\s+equals\s+(\d+)', t)
    if exact_match:
        field, expected = exact_match.group(1), int(exact_match.group(2))
        value = _extract_field(output, field)
        if value is None:
            return False, f"Field '{field}' not found in output"
        try:
            actual = int(value)
            passed = actual == expected
            return passed, f"'{field}' = {actual}, expected {expected}"
        except (ValueError, TypeError):
            return False, f"'{field}' value '{value}' is not an integer"

    # ── Numeric range: "X is between N and M" ─────────────────────────────
    range_match = re.search(
        r'["\']?(\w+)["\']?\s+is\s+between\s+(\d+)\s+and\s+(\d+)', t
    )
    if range_match:
        field = range_match.group(1)
        lo, hi = int(range_match.group(2)), int(range_match.group(3))
        value = _extract_field(output, field)
        if value is None:
            return False, f"Field '{field}' not found in output"
        try:
            actual = int(value)
            passed = lo <= actual <= hi
            return passed, f"'{field}' = {actual}, expected [{lo}, {hi}]"
        except (ValueError, TypeError):
            return False, f"'{field}' value '{value}' is not an integer"

    # ── String inclusion: "includes 'X'" / "contains 'X'" ─────────────────
    include_match = re.search(r'(?:includes?|contains?)\s+["\']([^"\']+)["\']', t)
    if include_match:
        needle = include_match.group(1)
        # also check JSON field values
        passed = needle.lower() in output.lower()
        return passed, f"{'Found' if passed else 'Not found'}: '{needle}' in output"

    # ── String exclusion: "does not include 'X'" / "not contain 'X'" ──────
    exclude_match = re.search(
        r'(?:does\s+not\s+include?|not\s+contain?|excludes?)\s+["\']([^"\']+)["\']', t
    )
    if exclude_match:
        needle = exclude_match.group(1)
        passed = needle.lower() not in output.lower()
        return passed, f"{'Correctly absent' if passed else 'Found unexpectedly'}: '{needle}'"

    # ── Enum membership: "is one of [A, B, C]" ────────────────────────────
    enum_match = re.search(r'is\s+one\s+of\s+\[([^\]]+)\]', t)
    if enum_match:
        options = [o.strip().strip("'\"") for o in enum_match.group(1).split(",")]
        field_match = re.search(r'["\']?(\w+)["\']?\s+is\s+one\s+of', t)
        if field_match:
            field = field_match.group(1)
            value = _extract_field(output, field)
            if value is None:
                return False, f"Field '{field}' not found in output"
            passed = str(value).strip("'\"") in options
            return passed, f"'{field}' = '{value}', allowed: {options}"

    # ── Has keys: "has keys X, Y, Z" / "contains keys" ────────────────────
    keys_match = re.search(r'has\s+(?:keys?|fields?)\s+(.+)', t)
    if keys_match:
        keys_raw = keys_match.group(1)
        keys = [k.strip().strip("'\"") for k in re.split(r"[,\s]+and\s+|,\s*", keys_raw)]
        try:
            parsed = json.loads(out_stripped)
            if isinstance(parsed, dict):
                missing = [k for k in keys if k not in parsed]
                passed = len(missing) == 0
                return passed, (
                    "All required keys present" if passed
                    else f"Missing keys: {missing}"
                )
        except json.JSONDecodeError:
            return False, "Output is not valid JSON; cannot check keys"

    # ── Word count limit: "N words or fewer" ──────────────────────────────
    wc_match = re.search(r'(\d+)\s+words?\s+or\s+fewer', t)
    if wc_match:
        limit = int(wc_match.group(1))
        actual = len(out_stripped.split())
        passed = actual <= limit
        return passed, f"{actual} words, limit {limit}"

    # ── Regex: "matches /pattern/" ─────────────────────────────────────────
    regex_match = re.search(r'matches?\s+/([^/]+)/', t)
    if regex_match:
        pattern = regex_match.group(1)
        try:
            passed = bool(re.search(pattern, output))
            return passed, f"Pattern /{pattern}/ {'matched' if passed else 'did not match'}"
        except re.error as e:
            return False, f"Invalid regex: {e}"

    # ── No rule matched ────────────────────────────────────────────────────
    return None


def _extract_field(output: str, field: str) -> Any:
    """Try to extract a named field from JSON output. Returns None if not found."""
    try:
        parsed = json.loads(output.strip())
        if isinstance(parsed, dict) and field in parsed:
            return parsed[field]
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: regex search for "field": value
    m = re.search(rf'["\']?{re.escape(field)}["\']?\s*:\s*([^\n,}}]+)', output)
    return m.group(1).strip().strip('"\'') if m else None
```

### 6.2 LLM judge

```python
JUDGE_SYSTEM = """You are a strict, precise test grader for an AI skill evaluation system.

The skill was given this user prompt:
<prompt>{prompt}</prompt>

The skill produced this output:
<output>{output}</output>

Evaluate this single expectation:
<expectation>{expectation}</expectation>

Rules:
- Be strict. Only pass if the expectation is clearly and unambiguously met.
- Base your decision ONLY on the output shown. Do not assume what the skill intended.
- Your response must be EXACTLY a JSON object with two fields: "passed" (boolean) and
  "evidence" (one sentence explaining your decision).
- No prose. No markdown fences. Just the JSON object.

Example valid response:
{"passed": true, "evidence": "The output contains a JSON object with word_count field set to 30."}"""

def llm_judge(
    expectation_text: str,
    output: str,
    prompt: str,
    provider: SkillUnitProvider,
) -> tuple[bool, str]:
    system = JUDGE_SYSTEM.format(
        prompt=prompt, output=output[:3000], expectation=expectation_text
    )
    response = provider.complete(system="", user=system, max_tokens=200)
    raw = response.strip()
    raw = re.sub(r"^```[a-z]*\n?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        result = json.loads(raw)
        return bool(result.get("passed", False)), str(result.get("evidence", ""))
    except json.JSONDecodeError:
        return False, f"Judge returned unparseable response: {raw[:120]}"
```

### 6.3 Grade dispatcher

```python
import time
from skillunit.models import Expectation, OracleType, ExpectationResult

def grade_expectation(
    expectation: Expectation,
    output: str,
    prompt: str,
    eval_id: int,
    provider: SkillUnitProvider,
) -> ExpectationResult:
    t0 = time.perf_counter()

    oracle_used = expectation.oracle
    passed, evidence = False, ""

    if expectation.oracle == OracleType.DETERMINISTIC:
        result = try_deterministic(expectation.text, output)
        if result is None:
            raise ValueError(
                f"Expectation declared 'deterministic' but no rule matched:\n"
                f"  '{expectation.text}'\n"
                f"Either add a matching deterministic rule or change oracle to 'auto'."
            )
        passed, evidence = result

    elif expectation.oracle == OracleType.LLM_JUDGE:
        passed, evidence = llm_judge(expectation.text, output, prompt, provider)

    else:  # AUTO: try deterministic first, fall back to llm-judge
        result = try_deterministic(expectation.text, output)
        if result is not None:
            passed, evidence = result
            oracle_used = OracleType.DETERMINISTIC
        else:
            passed, evidence = llm_judge(expectation.text, output, prompt, provider)
            oracle_used = OracleType.LLM_JUDGE

    return ExpectationResult(
        eval_id=eval_id,
        text=expectation.text,
        passed=passed,
        evidence=evidence,
        oracle_used=oracle_used,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
```

**Test `test_grader.py` before moving on.** Write unit tests for every
deterministic rule using synthetic outputs. Do not use real API calls in unit
tests — mock the LLM judge.

---

## Phase 7 — Mock layer (`skillunit/mock.py`)

The mock layer is optional. When `mocks.json` exists and `--mock` is passed,
it intercepts any tool invocation string the executor produces and replaces it
with the fixture response before passing to the grader.

In this first version, mocking works at the **output level** rather than at the
API tool-call level: if the mock definitions contain a `bash` rule matching
`npm install`, and the skill's output mentions running `npm install`, the runner
substitutes the fixture. For a future version with true tool-call interception,
implement as an API middleware layer.

```python
import re
import json
from skillunit.models import MockDefinitions, MockRule


def apply_mocks(output: str, mocks: MockDefinitions | None) -> str:
    """
    Post-process executor output: replace any mention of a mocked tool call
    result with the fixture return value.
    This is a simple string-level substitution for v0.1.
    """
    if mocks is None:
        return output
    return output  # v0.1: pass-through; full implementation in Phase 7 extension


def find_mock(tool_name: str, args: dict, mocks: MockDefinitions) -> object | None:
    """
    Given a tool name and its arguments, return the fixture response if a
    matching mock rule exists. Returns None if no rule matches.

    Matching logic:
    - For each rule in mocks.rules[tool_name]:
      - For each key in rule.match:
        - If rule.match[key] ends with *, do prefix match
        - Otherwise, do exact match against args[key]
      - All keys must match for the rule to fire
    """
    rules = mocks.rules.get(tool_name, [])
    for rule in rules:
        if _rule_matches(rule, args):
            return rule.returns
    return None


def _rule_matches(rule: MockRule, args: dict) -> bool:
    for key, pattern in rule.match.items():
        actual = args.get(key, "")
        if isinstance(pattern, str) and pattern.endswith("*"):
            if not str(actual).startswith(pattern[:-1]):
                return False
        elif actual != pattern:
            return False
    return True
```

---

## Phase 8 — Runner (`skillunit/runner.py`)

The runner orchestrates all phases for a single `skillunit run` invocation.

```python
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from skillunit.models import (
    CanonicalSkill, EvalSuite, EvalResult, GradingReport, ExpectationResult,
    ExecutionMetrics, OracleType,
)
from skillunit.parser import parse_skill
from skillunit.loader import load_evals, load_mocks
from skillunit.executor import run_trigger_probe, run_task
from skillunit.grader import grade_expectation
from skillunit.providers.base import SkillUnitProvider

console = Console()


def run_suite(
    skill_path: Path,
    evals_path: Path | None,
    provider: SkillUnitProvider,
    grader_provider: SkillUnitProvider | None = None,  # defaults to same as executor
    use_mocks: bool = False,
    run_trigger_tests: bool = True,
    output_dir: Path = Path("results"),
) -> GradingReport:

    grader_provider = grader_provider or provider
    skill = parse_skill(skill_path)
    suite = load_evals(skill_path, evals_path)
    mocks = load_mocks(skill_path) if use_mocks else None

    # Validate skill_name matches
    if suite.skill_name != skill.name:
        raise ValueError(
            f"skill_name in evals.json ('{suite.skill_name}') does not match "
            f"SKILL.md name ('{skill.name}'). Fix one to match the other."
        )

    console.print(f"\n[bold]SkillUnit[/bold] — [cyan]{skill.name}[/cyan]")
    console.print(f"Provider : {provider.model_id()}")
    console.print(f"Evals    : {len(suite.evals)} test cases")
    console.print(f"Mocks    : {'enabled' if use_mocks and mocks else 'disabled'}\n")

    all_expectation_results: list[ExpectationResult] = []
    eval_results: list[EvalResult] = []
    all_metrics: list[ExecutionMetrics] = []

    for eval_case in suite.evals:
        console.rule(f"Eval {eval_case.id}")

        # ── Trigger test ──────────────────────────────────────────────────
        triggered = None
        if run_trigger_tests:
            triggered = run_trigger_probe(skill, eval_case.prompt, provider)
            trigger_ok = (triggered == eval_case.should_trigger)
            icon = "✓" if trigger_ok else "✗"
            expected = "trigger" if eval_case.should_trigger else "no trigger"
            actual = "triggered" if triggered else "not triggered"
            console.print(f"  {icon} Trigger: expected {expected}, got {actual}")

            # If trigger failed as expected (should_trigger=False), skip task
            if not trigger_ok and not eval_case.should_trigger:
                console.print("    [yellow]False positive trigger — marking as FAIL[/yellow]")
            elif not triggered and eval_case.should_trigger:
                console.print("    [yellow]Skill did not trigger — skipping task expectations[/yellow]")
                # Mark all expectations as SKIP
                for exp in eval_case.expectations:
                    all_expectation_results.append(ExpectationResult(
                        eval_id=eval_case.id,
                        text=exp.text,
                        passed=False,
                        evidence="Skipped: skill did not trigger",
                        oracle_used=OracleType.AUTO,
                    ))
                eval_results.append(EvalResult(
                    eval_id=eval_case.id,
                    prompt=eval_case.prompt,
                    triggered=triggered,
                    output="",
                    expectation_results=[],
                    metrics=ExecutionMetrics(),
                    pass_rate=0.0,
                ))
                continue

        # ── Task execution ────────────────────────────────────────────────
        console.print(f"  Running executor...", end=" ")
        output, metrics = run_task(skill, eval_case.prompt, provider, mocks)
        all_metrics.append(metrics)
        console.print(f"done ({metrics.duration_seconds:.1f}s)")
        preview = output[:100].replace("\n", " ")
        console.print(f"  Output: {preview}{'...' if len(output) > 100 else ''}")

        # ── Grade expectations ────────────────────────────────────────────
        exp_results: list[ExpectationResult] = []
        for exp in eval_case.expectations:
            result = grade_expectation(exp, output, eval_case.prompt, eval_case.id, grader_provider)
            exp_results.append(result)
            all_expectation_results.append(result)
            icon = "✓" if result.passed else "✗"
            oracle_tag = f"[{result.oracle_used.value}]"
            console.print(f"  {icon} {oracle_tag} {exp.text[:70]}")
            if not result.passed:
                console.print(f"       → {result.evidence}")

        n_passed = sum(1 for r in exp_results if r.passed)
        n_total = len(exp_results)
        pass_rate = n_passed / n_total if n_total > 0 else 0.0
        eval_results.append(EvalResult(
            eval_id=eval_case.id,
            prompt=eval_case.prompt,
            triggered=triggered,
            output=output,
            expectation_results=exp_results,
            metrics=metrics,
            pass_rate=pass_rate,
        ))

    # ── Aggregate ─────────────────────────────────────────────────────────
    total_passed = sum(1 for r in all_expectation_results if r.passed)
    total = len(all_expectation_results)
    overall_pass_rate = round(total_passed / total, 3) if total > 0 else 0.0

    report = GradingReport(
        expectations=all_expectation_results,
        summary={
            "passed": total_passed,
            "failed": total - total_passed,
            "total": total,
            "pass_rate": overall_pass_rate,
        },
        execution_metrics={
            "total_duration_seconds": sum(m.duration_seconds for m in all_metrics),
            "total_tokens": sum(m.tokens for m in all_metrics),
        },
        timing={"executor_model": provider.model_id()},
        eval_results=eval_results,
    )

    _print_summary(report, console)
    return report


def _print_summary(report: GradingReport, console: Console):
    pct = int(report.summary["pass_rate"] * 100)
    bar_len = 30
    filled = int(bar_len * report.summary["pass_rate"])
    bar = "█" * filled + "░" * (bar_len - filled)
    console.print(f"\n{'='*50}")
    console.print(f"  [{bar}] {pct}%")
    console.print(f"  Passed : {report.summary['passed']}/{report.summary['total']}")
    console.print(f"  Failed : {report.summary['failed']}/{report.summary['total']}")
    console.print(f"{'='*50}\n")
    for r in report.expectations:
        if not r.passed:
            console.print(f"  ✗ [Eval {r.eval_id}] {r.text}")
            console.print(f"    → {r.evidence}")
```

---

## Phase 9 — Diff (`skillunit/diff.py`)

```python
import json
from pathlib import Path
from skillunit.models import DiffReport, ExpectationDiff, GradingReport


def load_grading(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_reports(before_path: Path, after_path: Path) -> DiffReport:
    before = load_grading(before_path)
    after = load_grading(after_path)

    # Build lookup: (eval_id, text) → passed
    def index(report: dict) -> dict[tuple[int, str], bool]:
        return {
            (e["eval_id"], e["text"]): e["passed"]
            for e in report.get("expectations", [])
        }

    before_idx = index(before)
    after_idx = index(after)
    all_keys = set(before_idx) | set(after_idx)

    regressions, fixes = [], []
    stable_passes = stable_fails = 0

    for key in sorted(all_keys):
        eval_id, text = key
        b = before_idx.get(key)
        a = after_idx.get(key)

        if b is True and a is False:
            change = "regression"
            regressions.append(ExpectationDiff(
                eval_id=eval_id, text=text, before=True, after=False, change_type=change))
        elif b is False and a is True:
            change = "fix"
            fixes.append(ExpectationDiff(
                eval_id=eval_id, text=text, before=False, after=True, change_type=change))
        elif b is True and a is True:
            stable_passes += 1
        else:
            stable_fails += 1

    return DiffReport(
        before_path=str(before_path),
        after_path=str(after_path),
        regressions=regressions,
        fixes=fixes,
        stable_passes=stable_passes,
        stable_fails=stable_fails,
        net_change=len(fixes) - len(regressions),
    )
```

---

## Phase 10 — Coverage (`skillunit/coverage.py`)

**This is the most expensive feature. Read the design carefully before coding.**

### Design

For each section in `skill.sections`, ablate it from the body and re-run the
full grader. A section is "covered" by an eval if removing it changes the
grading outcome for at least one expectation of that eval.

To control cost, implement the stability filter: run each (section, eval) pair
`n_runs` times (default 2). A coverage signal is only counted if the outcome
difference is consistent across majority of runs.

```python
import copy
from skillunit.models import (
    CanonicalSkill, EvalSuite, SkillSection,
    SectionCoverageResult, CoverageReport,
)
from skillunit.executor import run_task
from skillunit.grader import grade_expectation
from skillunit.providers.base import SkillUnitProvider
from rich.console import Console

console = Console()


def ablate_section(skill: CanonicalSkill, section: SkillSection) -> str:
    """Return skill body with the given section removed."""
    body = skill.body
    return body[:section.char_start] + body[section.char_end:]


def grade_full(skill: CanonicalSkill, eval_case, provider, n_runs: int) -> list[bool]:
    """Run the eval n_runs times and return list of per-run overall pass booleans."""
    results = []
    for _ in range(n_runs):
        output, _ = run_task(skill, eval_case.prompt, provider)
        passed_all = all(
            grade_expectation(exp, output, eval_case.prompt, eval_case.id, provider).passed
            for exp in eval_case.expectations
        )
        results.append(passed_all)
    return results


def grade_ablated(skill: CanonicalSkill, section: SkillSection,
                  eval_case, provider, n_runs: int) -> list[bool]:
    ablated_body = ablate_section(skill, section)
    results = []
    for _ in range(n_runs):
        output, _ = run_task(skill, eval_case.prompt, provider,
                             skill_body_override=ablated_body)
        passed_all = all(
            grade_expectation(exp, output, eval_case.prompt, eval_case.id, provider).passed
            for exp in eval_case.expectations
        )
        results.append(passed_all)
    return results


def majority(bools: list[bool]) -> bool:
    return sum(bools) > len(bools) / 2


def run_coverage(
    skill_path,
    suite: EvalSuite,
    provider: SkillUnitProvider,
    n_runs: int = 2,
) -> CoverageReport:
    from skillunit.parser import parse_skill
    from pathlib import Path
    skill = parse_skill(Path(skill_path))

    total_calls = 0
    section_results: list[SectionCoverageResult] = []

    for section in skill.sections:
        evals_covered = []
        evals_tested = []

        for eval_case in suite.evals:
            if not eval_case.expectations:
                continue

            # Run full body (n_runs times)
            full_outcomes = grade_full(skill, eval_case, provider, n_runs)
            total_calls += n_runs
            stable_full = majority(full_outcomes)

            # Run ablated body (n_runs times)
            ablated_outcomes = grade_ablated(skill, section, eval_case, provider, n_runs)
            total_calls += n_runs
            stable_ablated = majority(ablated_outcomes)

            evals_tested.append(eval_case.id)
            if stable_full != stable_ablated:
                evals_covered.append(eval_case.id)

        n_covered = len(evals_covered)
        n_tested = len(evals_tested)
        score = round(n_covered / n_tested, 2) if n_tested > 0 else 0.0

        if score == 0.0:
            verdict = "DEAD"
            rec = (
                f"Section '{' > '.join(section.heading_path)}' never affects output. "
                f"Remove it to reduce context token usage, or add evals that exercise it."
            )
        elif score < 0.34:
            verdict = "WEAKLY_COVERED"
            rec = f"Add more evals targeting '{' > '.join(section.heading_path)}'."
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
            evals_covered=evals_covered,
            evals_tested=evals_tested,
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
```

---

## Phase 11 — Writer (`skillunit/writer.py`)

```python
import json
from pathlib import Path
from skillunit.models import GradingReport, CoverageReport, DiffReport


def write_grading(report: GradingReport, output_dir: Path) -> Path:
    """Write grading.json in Anthropic-native schema."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "grading.json"

    # Serialize to Anthropic schema exactly
    data = {
        "expectations": [
            {
                "eval_id": r.eval_id,
                "text": r.text,
                "passed": r.passed,
                "evidence": r.evidence,
            }
            for r in report.expectations
        ],
        "summary": report.summary,
        "execution_metrics": report.execution_metrics,
        "timing": report.timing,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_coverage(report: CoverageReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # coverage.json
    json_path = output_dir / "coverage.json"
    json_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")

    # coverage.md — human-readable
    md_path = output_dir / "coverage.md"
    lines = [
        f"# Coverage report: {report.skill_name}",
        f"\nOverall coverage: **{int(report.overall_coverage * 100)}%**",
        f"Executor calls made: {report.executor_calls_made}",
        "\n| Section | Score | Verdict |",
        "|---|---|---|",
    ]
    for s in report.sections:
        path_str = " > ".join(s.heading_path)
        lines.append(f"| {path_str} | {s.coverage_score:.2f} | {s.verdict} |")

    if report.dead_sections:
        lines.append("\n## Dead instructions (score 0.0)\n")
        for sid in report.dead_sections:
            sec = next(s for s in report.sections if s.section_id == sid)
            lines.append(f"- `{sid}`: {sec.recommendation}")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def write_diff(report: DiffReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "diff.json"
    path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    return path
```

---

## Phase 12 — CLI (`skillunit/cli.py`)

Use Typer. Every command is a function decorated with `@app.command()`.

```python
import typer
from pathlib import Path
from rich.console import Console
from typing import Annotated, Optional

app = typer.Typer(
    name="skillunit",
    help="A portable, framework-agnostic testing framework for agent skills.",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    skill: Annotated[Path, typer.Argument(help="Path to skill directory")],
    evals: Annotated[Optional[Path], typer.Option(help="Path to evals.json")] = None,
    output: Annotated[Path, typer.Option(help="Output directory")] = Path("results"),
    provider: Annotated[str, typer.Option(help="Provider: anthropic, openai, local")] = "anthropic",
    model: Annotated[Optional[str], typer.Option(help="Model override")] = None,
    mock: Annotated[bool, typer.Option(help="Enable mock layer")] = False,
    no_trigger: Annotated[bool, typer.Option(help="Skip trigger tests")] = False,
    min_pass_rate: Annotated[float, typer.Option(help="Minimum pass rate (CI gate)")] = 0.0,
):
    """Run the full test suite for a skill."""
    from skillunit.providers import make_provider
    from skillunit.runner import run_suite
    from skillunit.writer import write_grading

    p = make_provider(f"{provider}:{model}" if model else provider)
    report = run_suite(
        skill_path=skill,
        evals_path=evals,
        provider=p,
        use_mocks=mock,
        run_trigger_tests=not no_trigger,
        output_dir=output,
    )
    path = write_grading(report, output)
    console.print(f"\nReport written to [cyan]{path}[/cyan]")

    if min_pass_rate > 0 and report.summary["pass_rate"] < min_pass_rate:
        console.print(
            f"[red]FAIL: pass rate {report.summary['pass_rate']:.2f} "
            f"< required {min_pass_rate:.2f}[/red]"
        )
        raise typer.Exit(1)


@app.command()
def diff(
    before: Annotated[Path, typer.Argument(help="Path to first grading.json")],
    after: Annotated[Path, typer.Argument(help="Path to second grading.json")],
    output: Annotated[Path, typer.Option(help="Output directory")] = Path("results"),
):
    """Compare two grading.json files and show regressions and fixes."""
    from skillunit.diff import diff_reports
    from skillunit.writer import write_diff

    report = diff_reports(before, after)

    if report.regressions:
        console.print(f"\n[red]Regressions ({len(report.regressions)}):[/red]")
        for r in report.regressions:
            console.print(f"  ✗ [Eval {r.eval_id}] {r.text}")
    if report.fixes:
        console.print(f"\n[green]Fixes ({len(report.fixes)}):[/green]")
        for f in report.fixes:
            console.print(f"  ✓ [Eval {f.eval_id}] {f.text}")

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
    evals: Annotated[Optional[Path], typer.Option()] = None,
    output: Annotated[Path, typer.Option()] = Path("results"),
    provider: Annotated[str, typer.Option()] = "anthropic",
    model: Annotated[Optional[str], typer.Option()] = None,
    runs: Annotated[int, typer.Option(help="Runs per (section, eval) pair")] = 2,
    threshold: Annotated[float, typer.Option(help="Minimum section coverage (CI gate)")] = 0.0,
    confirm: Annotated[bool, typer.Option(help="Skip cost confirmation prompt")] = False,
):
    """Run ablation-based coverage analysis on the skill body."""
    from skillunit.providers import make_provider
    from skillunit.loader import load_evals
    from skillunit.parser import parse_skill
    from skillunit.coverage import run_coverage
    from skillunit.writer import write_coverage

    p = make_provider(f"{provider}:{model}" if model else provider)
    skill_obj = parse_skill(skill)
    suite = load_evals(skill, evals)

    n_sections = len(skill_obj.sections)
    n_evals = len(suite.evals)
    est_calls = n_sections * n_evals * runs * 2  # full + ablated
    console.print(f"\nCoverage analysis: {n_sections} sections × {n_evals} evals × {runs} runs")
    console.print(f"Estimated executor calls: ~{est_calls}")

    if est_calls > 50 and not confirm:
        typer.confirm(f"This will make ~{est_calls} API calls. Continue?", abort=True)

    report = run_coverage(skill, suite, p, n_runs=runs)
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
    """Scaffold a new skill directory with SKILL.md and evals/evals.json."""
    skill_dir = output / name
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: >\n  Describe what this skill does and when to trigger it.\n---\n\n"
        f"# {name.replace('-', ' ').title()}\n\n## What this skill does\n\n[Describe the skill]\n\n"
        f"## Steps\n\n1. Step one\n2. Step two\n\n## Output format\n\n[Describe expected output]\n",
        encoding="utf-8",
    )
    (evals_dir / "evals.json").write_text(
        json.dumps({
            "skill_name": name,
            "evals": [{
                "id": 1,
                "prompt": "Example prompt that should trigger this skill",
                "expected_output": "Description of what success looks like",
                "files": [],
                "should_trigger": True,
                "expectations": [
                    {"text": "The output is a valid JSON object", "oracle": "deterministic"},
                    {"text": "The output addresses the user's request", "oracle": "llm-judge"},
                ],
            }]
        }, indent=2),
        encoding="utf-8",
    )
    (evals_dir / "mocks.json").write_text("{}\n", encoding="utf-8")
    console.print(f"\n[green]Scaffold created at {skill_dir}[/green]")
    console.print(f"  Edit [cyan]{skill_dir}/SKILL.md[/cyan] to define your skill")
    console.print(f"  Edit [cyan]{evals_dir}/evals.json[/cyan] to add test cases")
    console.print(f"\nThen run: [bold]skillunit run {skill_dir}[/bold]")


@app.command()
def matrix(
    skill: Annotated[Path, typer.Argument()],
    evals: Annotated[Optional[Path], typer.Option()] = None,
    output: Annotated[Path, typer.Option()] = Path("results"),
    providers: Annotated[list[str], typer.Option("--provider")] = ["anthropic"],
):
    """Run the test suite against multiple providers/models and compare."""
    import json
    from skillunit.providers import make_provider
    from skillunit.runner import run_suite
    from skillunit.writer import write_grading

    matrix_results = {}
    for prov_str in providers:
        console.rule(f"Provider: {prov_str}")
        p = make_provider(prov_str)
        report = run_suite(skill_path=skill, evals_path=evals, provider=p, output_dir=output)
        write_grading(report, output / prov_str.replace(":", "_"))
        matrix_results[prov_str] = report.summary

    # Print matrix summary table
    console.print("\n[bold]Matrix summary[/bold]\n")
    header = f"{'Provider':<30} {'Pass rate':>10} {'Passed':>8} {'Failed':>8}"
    console.print(header)
    console.print("-" * 60)
    for prov, summary in matrix_results.items():
        pct = f"{int(summary['pass_rate'] * 100)}%"
        console.print(f"{prov:<30} {pct:>10} {summary['passed']:>8} {summary['failed']:>8}")

    matrix_path = output / "matrix.json"
    matrix_path.write_text(json.dumps(matrix_results, indent=2), encoding="utf-8")
    console.print(f"\nMatrix results: [cyan]{matrix_path}[/cyan]")


if __name__ == "__main__":
    app()
```

---

## Phase 13 — Example skill (for manual testing)

Create a working example skill that Claude Code can use to validate the entire
pipeline end-to-end. Put it at `example-skill/`.

**`example-skill/SKILL.md`:**
```yaml
---
name: text-analyzer
description: >
  Analyze a block of text and return structured statistics including word count,
  sentence count, top keywords, reading level, and a one-sentence summary.
  Use this skill when the user asks to analyze, profile, or get statistics about
  any text. Trigger on: "analyze this text", "word count", "reading level",
  "summarize this", "key words". Do NOT use for full document creation or translation.
---

# Text Analyzer

Return a single JSON object (no prose, no markdown fences) with this schema:
{ "word_count": int, "sentence_count": int, "top_keywords": [str],
  "reading_level": "elementary"|"middle"|"high_school"|"college"|"graduate",
  "summary": str }

## Rules
1. Count words by splitting on whitespace. Hyphenated words count as one.
2. Count sentences by terminal punctuation (. ! ?).
3. Top keywords: 3-5 words, most significant first, no stop words.
4. Reading level: average words/sentence: ≤10=elementary, 11-15=middle,
   16-20=high_school, 21-25=college, >25=graduate.
5. Summary: one declarative sentence, ≤25 words.
6. Output ONLY the JSON. No explanation. No markdown.
```

**`example-skill/evals/evals.json`:** (use the 5-eval set from earlier in this document)

---

## Phase 14 — Tests

Write pytest tests for every module. Run `pytest tests/ -v` after each phase.
All tests must pass before moving to the next phase.

### `tests/test_parser.py`
- Test with valid Anthropic SKILL.md → correct name, description, sections
- Test missing frontmatter → raises SkillParseError
- Test missing `name` field → raises SkillParseError
- Test section parsing: verify section IDs are stable and non-overlapping

### `tests/test_grader.py`
- Test every deterministic rule with a synthetic output string
- Test `oracle=deterministic` on unmatched text → raises ValueError
- Test `oracle=auto` falls back correctly (mock the LLM judge to avoid API calls)
- Test the LLM judge parser handles malformed JSON gracefully

### `tests/test_diff.py`
- Test regression detection (✓→✗)
- Test fix detection (✗→✓)
- Test stable passes and fails counted correctly
- Test net_change arithmetic

### `tests/test_loader.py`
- Test valid evals.json loads correctly
- Test missing skill_name → raises ValueError
- Test both string and dict expectation formats parse correctly

---

## Phase 15 — CI workflow (`skillunit-ci.yml`)

Create this at `.github/workflows/skillunit-ci.yml` in the repo root:

```yaml
name: SkillUnit CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v --tb=short
      - run: |
          skillunit run ./example-skill \
            --min-pass-rate 0.8 \
            --output ./ci-results
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: skillunit-results
          path: ci-results/
```

---

## Implementation order and checkpoints

Follow this exact order. Do not skip phases. After each checkpoint, verify
the listed condition before continuing.

| Phase | Module | Checkpoint |
|---|---|---|
| 1 | `models.py`, `pyproject.toml` | `pip install -e .` succeeds; `from skillunit.models import CanonicalSkill` works |
| 2 | `parser.py` | `test_parser.py` all pass |
| 3 | `loader.py` | `test_loader.py` all pass |
| 4 | `providers/` | `AnthropicProvider().complete("ping", "say hi")` returns text |
| 5 | `executor.py` | trigger probe returns True for clear match, False for clear non-match |
| 6 | `grader.py` | `test_grader.py` all pass; zero API calls for deterministic rules |
| 7 | `mock.py` | `find_mock("bash", {"command": "npm install"}, mocks)` returns fixture |
| 8 | `runner.py` | `skillunit run ./example-skill` completes and prints a summary |
| 9 | `diff.py` | `test_diff.py` all pass |
| 10 | `coverage.py` | `skillunit coverage ./example-skill --runs 1` completes without error |
| 11 | `writer.py` | `grading.json` produced by Phase 8 passes Anthropic schema validation |
| 12 | `cli.py` | `skillunit --help` shows all commands; `skillunit init test-skill` creates correct files |
| 13 | example-skill | `skillunit run ./example-skill` produces pass rate ≥ 0.7 |
| 14 | tests/ | `pytest tests/ -v` all green |
| 15 | CI | `.github/workflows/skillunit-ci.yml` runs successfully |

---

## Error handling conventions

- All user-facing errors use `rich` formatting: `[red]ERROR:[/red]` prefix.
- Raise typed exceptions from library code; catch and format in CLI.
- Custom exceptions to define in `models.py`:
  - `SkillParseError` — malformed SKILL.md
  - `EvalsValidationError` — malformed evals.json
  - `SkillNameMismatchError` — skill_name in evals != name in skill
  - `DeterministicOracleError` — deterministic oracle declared but no rule matched
  - `UnmockedToolCallError` — tool call made in strict mock mode with no matching rule

---

## Important implementation notes

1. **Never hardcode API keys.** Always read from environment variables.
   `AnthropicProvider` reads `ANTHROPIC_API_KEY`. `OpenAIProvider` reads `OPENAI_API_KEY`.

2. **Grading.json schema is load-bearing.** The Anthropic eval-viewer reads
   `expectations[].text`, `expectations[].passed`, `expectations[].evidence` by
   exact field name. Do not rename these fields. Do not nest them differently.

3. **Coverage is expensive.** Always print estimated call count and require
   `--confirm` for suites above 50 calls unless `--confirm` is passed explicitly.

4. **Sections must not overlap.** The ablation logic assumes each section's
   `char_start`/`char_end` range is non-overlapping with all others. Verify
   this invariant in the parser with an assertion.

5. **Trigger probe uses description only.** The probe must not inject the full
   skill body — only `name` and `description`. This mirrors real Claude Code
   skill selection behavior.

6. **LLM judge outputs are non-deterministic.** Never use them in unit tests
   without mocking. All `test_grader.py` tests must mock `llm_judge`.
