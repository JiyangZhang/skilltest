from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class SkillParseError(Exception):
    pass

class EvalsValidationError(Exception):
    pass

class SkillNameMismatchError(Exception):
    pass


class SkillFormat(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class SkillSection(BaseModel):
    id: str
    heading_path: list[str]
    raw_text: str
    char_start: int
    char_end: int


class CanonicalSkill(BaseModel):
    name: str
    description: str
    body: str
    sections: list[SkillSection]
    source_format: SkillFormat
    source_path: str


class OracleType(str, Enum):
    """Supported expectation oracles."""
    AGENT_JUDGE = "agent-judge"  # Claude Code agent on host; can read/inspect artifact files
    PYTEST = "pytest"


class Expectation(BaseModel):
    text: str
    oracle: OracleType = OracleType.AGENT_JUDGE
    pytest_path: str | None = None  # path relative to skill dir; default tests/pytests when oracle=pytest
    rubric: list[str] = Field(default_factory=list)  # scoring criteria for llm-judge


class SetupStep(BaseModel):
    """A single setup or cleanup step: run a shell command or create a file."""
    shell: str | None = None    # shell command to run on the host (in skill dir)
    file: str | None = None     # file path to create, relative to the run workspace
    content: str | None = None  # file content (used with file)


class TestConstraints(BaseModel):
    """Execution limits for the agent under test."""
    timeout_seconds: float | None = None  # wall-clock timeout for the agent call
    max_steps: int | None = None          # max agentic turns (Docker: --max-turns)


class TestCase(BaseModel):
    id: int
    prompt: str = ""
    expected_output: str = ""
    files: list[str] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)
    input_dir: str | None = None
    task_file: str | None = None
    setup: list[SetupStep] = Field(default_factory=list)
    cleanup: list[SetupStep] = Field(default_factory=list)
    constraints: TestConstraints | None = None


class TestSuite(BaseModel):
    skill_name: str
    tests: list[TestCase]
    schema_version: int = 1



class ExpectationResult(BaseModel):
    test_id: int
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


class TestResult(BaseModel):
    test_id: int
    prompt: str
    output: str
    expectation_results: list[ExpectationResult]
    metrics: ExecutionMetrics
    pass_rate: float = 0.0


class GradingReport(BaseModel):
    expectations: list[ExpectationResult]
    summary: dict[str, Any]
    execution_metrics: dict[str, Any]
    timing: dict[str, Any]
    test_results: list[TestResult]


class SectionCoverageResult(BaseModel):
    section_id: str
    heading_path: list[str]
    coverage_score: float
    tests_covered: list[int]
    tests_tested: list[int]
    verdict: str
    recommendation: str


class CoverageReport(BaseModel):
    skill_name: str
    overall_coverage: float
    sections: list[SectionCoverageResult]
    dead_sections: list[str]
    executor_calls_made: int


class ExpectationDiff(BaseModel):
    test_id: int
    text: str
    before: bool
    after: bool
    change_type: str


class DiffReport(BaseModel):
    before_path: str
    after_path: str
    regressions: list[ExpectationDiff]
    fixes: list[ExpectationDiff]
    stable_passes: int
    stable_fails: int
    net_change: int
