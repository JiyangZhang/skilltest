# SkillUnit: A Universal, Framework-Agnostic Testing Framework for Agent Skills

**Proposal v2.0** — April 2026

---

## Problem Statement

Agent skills are the primitive units of agent behavior — yet they are tested informally, if at all. Both Anthropic (skill-creator v2, March 2026) and OpenAI (eval-skills, January 2026) have shipped first attempts at skill evaluation, but both solutions share three fundamental limitations:

1. **Product-locked** — Anthropic's evals require Claude Code subagents; OpenAI's require the Codex CLI. Neither runs standalone in CI.
2. **Incomplete test coverage** — neither framework unifies trigger testing with task testing, and neither has a regression diff tool.
3. **Format-specific** — neither can test skills written for the other platform.

SkillUnit is a **standalone, open-source Python framework** that brings JUnit-style discipline to agent skill development. It is format-agnostic (Anthropic and OpenAI skill formats both supported), provider-agnostic (Anthropic, OpenAI, or local LLMs), and installable anywhere with `pip install skillunit`.

---

## Key Highlights

### 1. Universal skill format support

SkillUnit normalizes both Anthropic and OpenAI skill formats into a single **canonical internal representation**. Neither format is privileged — both are source formats. The runner, grader, coverage analyzer, and diff tool all operate on the canonical form.

```
Anthropic SKILL.md  ──┐
                       ├──▶  CanonicalSkill  ──▶  run / grade / cover / diff
OpenAI    SKILL.md  ──┘
```

Both formats share a common structure (YAML frontmatter with `name` and `description`, followed by a Markdown body). SkillUnit's parser handles the surface differences transparently. A developer can test an OpenAI-format skill against the Anthropic API or vice versa — the provider and the skill format are independent choices.

```bash
skillunit run ./my-openai-skill  --provider anthropic
skillunit run ./my-anthropic-skill --provider openai
```

### 2. Coupled trigger + task testing in a single pass

The single biggest gap in all existing tooling. One `skillunit run` command tests both:

- **Trigger test** — given this prompt and the skill's `name` + `description`, would the agent invoke this skill?
- **Task test** — given the skill's full body as context, does the output satisfy the expectations?

A skill that doesn't trigger also fails its task expectations. A skill that triggers when it shouldn't is a false-positive failure. These are not separate workflows.

```json
{
  "id": 1,
  "prompt": "Analyze this text: 'The quick brown fox...'",
  "should_trigger": true,
  "expectations": [
    { "text": "The output is a valid JSON object",    "oracle": "deterministic" },
    { "text": "word_count is exactly 30",             "oracle": "deterministic" },
    { "text": "summary is a single sentence",         "oracle": "llm-judge"     }
  ]
}
```

### 3. Hybrid oracles — deterministic first, LLM judge only where needed

Every expectation declares its oracle type explicitly. Deterministic checks run first — they are fast, free, and fully reproducible with no API call. The LLM judge is invoked only for semantic expectations where no exact rule applies.

**Deterministic check library** — resolved by parsing the expectation text with a rule-based classifier:

| Expectation pattern | Resolved check (no API call) |
|---|---|
| `"is a valid JSON object"` | `json.loads(output)` succeeds |
| `"word_count is exactly 30"` | `parsed["word_count"] == 30` |
| `"is between 40 and 46"` | `40 <= value <= 46` |
| `"includes 'photosynthesis'"` | `"photosynthesis" in output` |
| `"does not include 'the'"` | `"the" not in value` |
| `"is one of [elementary, middle, high_school]"` | `value in enum` |
| `"has keys title, url, snippet"` | all keys present in JSON |
| `"matches /^\\{/"` | `re.search(pattern, output)` |
| `"is 25 words or fewer"` | `len(output.split()) <= 25` |

If no rule matches and `"oracle": "deterministic"` is declared, the runner raises an error rather than silently falling back to the LLM judge — preserving the determinism guarantee.

### 4. Coverage metric for skill instructions

> *"A good framework could help developers identify which parts of their skill body actually change behavior versus which are noise."*

SkillUnit implements **ablation-based coverage**. For each section of the SKILL.md body (parsed by Markdown heading and bullet group), the runner executes the eval twice: once with the full body, once with that section removed. If the grading outcome changes, the section has coverage over that test. If the outcome is identical, the section is noise.

```
skillunit coverage ./my-skill

Section: "Rules > Rule 1: count words by whitespace"
  Eval 1 (ablated): word_count changed from 30 → 27    COVERED
  Eval 2 (ablated): word_count changed from 14 → 12    COVERED
  Coverage: 2/2 = 1.00  ✓

Section: "Example > Output"
  Eval 1 (ablated): no change in any expectation        NOT COVERED
  Eval 2 (ablated): no change in any expectation        NOT COVERED
  Coverage: 0/2 = 0.00  ← candidate for removal
```

The coverage report surfaces two actionable findings:

- **Dead instructions** (score 0.0): lines in the skill body that no eval exercises. Either write a test that covers them, or delete them — they consume context tokens for no behavioral benefit.
- **Under-tested rules** (score < 0.5): instructions that only matter in edge cases not yet represented in the eval suite.

Coverage runs as `skillunit coverage ./my-skill` (separate from `run` because it doubles API calls). It outputs `coverage.json` and a `coverage.md` summary.

### 5. Mock environment for external dependencies

Skills that read files, call APIs, run bash commands, or query databases cannot be tested reproducibly without controlling those dependencies. SkillUnit's mock layer intercepts tool calls made by the executor and returns pre-defined fixture responses.

Mocks are defined in `evals/mocks.json`:

```json
{
  "read_file": [
    { "match": { "path": "report.csv" },
      "returns": "col1,col2\n1,2\n3,4" }
  ],
  "bash": [
    { "match": { "command": "npm install" },
      "returns": { "exit_code": 0, "stdout": "", "stderr": "" } },
    { "match": { "command": "npm run build" },
      "returns": { "exit_code": 1, "stdout": "", "stderr": "Error: missing module" } }
  ],
  "http_get": [
    { "match": { "url_pattern": "api.weather.com/*" },
      "returns": { "status": 200, "body": { "temp": 22, "condition": "sunny" } } }
  ]
}
```

When `--mock` is passed, any tool call matching a mock rule returns the fixture. Unmatched calls either raise an error (strict mode, default) or fall through to the real environment (passthrough mode, `--mock-passthrough`).

This makes three previously-impossible test scenarios routine:

- **Hermetic CI** — test a `deploy-app` skill without deploying anything
- **Error path testing** — return a failing exit code from `npm run build` and assert the skill handles it gracefully
- **Expensive API mocking** — test a skill that calls a paid third-party API without incurring costs per test run

### 6. `skillunit diff` — regression surface between versions

The first tool in the space to give developers a version-aware diff of test results. Points at two `grading.json` files and reports exactly which expectations changed — including whether the change is a regression or a fix.

```bash
skillunit diff results/v1/grading.json results/v2/grading.json
```

```
Regressions (✓ → ✗)  — v2 broke these:
  [Eval 4] top_keywords includes 'mitochondria'   (was passing, now failing)

Fixes (✗ → ✓)  — v2 fixed these:
  [Eval 1] summary is a single sentence            (was failing, now passing)
  [Eval 2] word_count is exactly 14                (was failing, now passing)

Stable passes:   26/31
Stable fails:     2/31
Net change:      +1 expectation passing
```

The diff is also written to `diff.json` for programmatic consumption (CI gates, changelogs).

### 7. Cross-model matrix testing

Parameterize the executor model to measure how a skill performs across provider model versions. Essential for catching model-sensitive skills before they reach production.

```bash
skillunit run ./my-skill \
  --model anthropic:claude-sonnet-4-6 \
  --model anthropic:claude-haiku-4-5  \
  --model openai:gpt-4o
```

Produces a `grading.json` with per-model pass rates and a `matrix.md` summary:

```
                        claude-sonnet-4-6   claude-haiku-4-5   gpt-4o
  Overall pass rate          0.94               0.81             0.87
  Trigger accuracy           1.00               0.93             0.97
  Deterministic checks       1.00               1.00             1.00
  LLM-judge checks           0.87               0.60             0.73
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        skillunit CLI                            │
│   run │ diff │ coverage │ init │ matrix                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │        Parser layer          │
              │  Anthropic SKILL.md format   │
              │  OpenAI    SKILL.md format   │
              │         ──────────           │
              │      CanonicalSkill          │
              │  { name, description, body,  │
              │    sections[], evals[] }     │
              └──────────────┬──────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│  Trigger probe  │ │    Executor     │ │  Mock layer     │
│                 │ │                 │ │                 │
│ Is name+desc    │ │ Inject skill    │ │ Intercept tool  │
│ sufficient to   │ │ body as system  │ │ calls; return   │
│ invoke skill?   │ │ prompt; call    │ │ fixture from    │
│                 │ │ provider API    │ │ mocks.json      │
└────────┬────────┘ └────────┬────────┘ └─────────────────┘
         │                   │
         └─────────┬─────────┘
                   │
          ┌────────▼────────┐
          │  Grader layer   │
          │                 │
          │ Deterministic   │  ← rule classifier, no API call
          │ assertions      │
          │                 │
          │ LLM-judge       │  ← grader model call only if needed
          │ assertions      │
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │  Writer layer   │
          │                 │
          │ grading.json    │  ← Anthropic-native schema
          │ coverage.json   │
          │ diff.json       │
          │ matrix.md       │
          └─────────────────┘
```

### Provider abstraction

The executor and grader are both provider-agnostic. The provider adapter interface is:

```python
class SkillUnitProvider(Protocol):
    def complete(self, system: str, user: str) -> str: ...
    def model_id(self) -> str: ...

# Built-in adapters
AnthropicProvider(model="claude-sonnet-4-6")
OpenAIProvider(model="gpt-4o")
LocalProvider(base_url="http://localhost:11434")   # Ollama / LM Studio
```

Third-party adapters can be registered via a plugin entry point — making SkillUnit extensible to any API-compatible provider without modifying the core.

---

## Implementation Plan

### Phase 1 — Core runner (weeks 1–3)

**Goal:** working `skillunit run` command with schema-compatible output.

- `skillunit/parser.py` — parse Anthropic and OpenAI SKILL.md into `CanonicalSkill`
- `skillunit/loader.py` — load and validate `evals/evals.json`; enforce `skill_name` contract
- `skillunit/providers/` — `AnthropicProvider`, `OpenAIProvider`, `LocalProvider`
- `skillunit/executor.py` — inject canonical skill body as system prompt; call provider; return `(output, metrics)`
- `skillunit/grader.py` — rule classifier for deterministic checks; LLM-judge fallback
- `skillunit/writer.py` — serialize to `grading.json` (Anthropic-native schema)
- `skillunit/cli.py` — `skillunit run` with `--skill`, `--evals`, `--output`, `--provider`, `--model` flags
- PyPI packaging and publish

**Deliverable:** `pip install skillunit && skillunit run ./my-skill` works for both Anthropic and OpenAI skill formats.

### Phase 2 — Trigger testing + hybrid oracles (weeks 4–5)

**Goal:** couple trigger and task tests; make oracle type explicit and enforced.

- Add `should_trigger` to `evals.json` schema (optional, defaults to `true`)
- Implement trigger probe: lightweight call that checks whether the model would invoke the skill given the prompt, `name`, and `description` alone
- Expand deterministic check library to cover all patterns in the table above
- `"oracle": "deterministic"` raises `DeterministicOracleError` if no rule matches — no silent fallback
- Trigger failure short-circuits task expectations with `SKIP (trigger failed)` status
- False-positive trigger (`should_trigger: false`) reported as `FAIL (unexpected trigger)`

**Deliverable:** single `skillunit run` produces trigger accuracy and task pass rate as separate reported metrics.

### Phase 3 — Mock environment (weeks 6–7)

**Goal:** hermetic, reproducible tests for skills with external dependencies.

- `skillunit/mock.py` — intercept tool calls during executor run; match against `evals/mocks.json` rules
- Support match patterns: exact string, glob, regex
- Strict mode (default): unmatched tool call raises `UnmockedToolCallError`
- Passthrough mode (`--mock-passthrough`): unmatched calls execute normally
- Mock coverage report: which mock rules were exercised by which evals
- `skillunit init` scaffold generates an empty `mocks.json` template

**Deliverable:** `--mock` flag enables hermetic testing; `mocks.json` schema documented and validated.

### Phase 4 — Coverage analysis (weeks 8–9)

**Goal:** per-section coverage scores to identify dead instructions and undertested rules.

- `skillunit/coverage.py` — parse SKILL.md body into sections (by heading + bullet group)
- Ablation runner: for each section × each eval, run executor with section removed; compare grading outcome
- Aggregate into per-section coverage score (0.0–1.0)
- `coverage.json` — machine-readable coverage data
- `coverage.md` — human-readable summary with color-coded scores and actionable recommendations
- `skillunit coverage ./my-skill --threshold 0.5` — exits non-zero if any section scores below threshold

**Deliverable:** `skillunit coverage` command; `coverage.json` and `coverage.md` outputs.

### Phase 5 — Diff, matrix, and CI integration (weeks 10–11)

**Goal:** version-aware regression detection, cross-model matrix, and CI-ready tooling.

- `skillunit diff <grading_a.json> <grading_b.json>` — produce human-readable and machine-readable diff; classify each change as regression, fix, or stable
- `--model` flag accepts multiple values; matrix run produces per-model pass rates
- `matrix.md` summary table comparing all models across all evals
- `--min-pass-rate 0.8` flag: non-zero exit if overall pass rate falls below threshold (CI gate)
- `--min-trigger-rate 0.9` flag: separate CI gate for trigger accuracy
- GitHub Actions workflow template (`skillunit-ci.yml`) ships in repo

**Deliverable:** `skillunit diff`, matrix testing, and full CI integration.

### Phase 6 — Skill-creator compatibility and self-hosting (week 12)

**Goal:** zero-friction interop with Anthropic's ecosystem; SkillUnit ships as its own skill.

- Validate `grading.json` is bit-compatible with Anthropic's `eval-viewer/generate_review.py`
- Validate `grading.json` is compatible with `scripts/aggregate_benchmark.py`
- Write SkillUnit itself as a `SKILL.md` — invoke via `/skillunit` in Claude Code
- Documentation site (README + GitHub Pages)
- Contribution guide for third-party provider adapters

**Deliverable:** full interop with Anthropic's skill-creator viewer; SkillUnit installable as a Claude Code skill.

---

## File Layout

```
skillunit/                         ← PyPI package
├── cli.py                         ← entry point: run, diff, coverage, init, matrix
├── parser.py                      ← Anthropic + OpenAI → CanonicalSkill
├── loader.py                      ← evals.json validation
├── executor.py                    ← skill execution against provider
├── grader.py                      ← deterministic checks + LLM-judge
├── coverage.py                    ← ablation-based coverage analysis
├── mock.py                        ← tool call interception
├── diff.py                        ← grading.json comparison
├── writer.py                      ← grading.json, coverage.json, diff.json
└── providers/
    ├── base.py                    ← SkillUnitProvider protocol
    ├── anthropic.py
    ├── openai.py
    └── local.py                   ← Ollama / LM Studio

my-skill/                          ← a skill under test (any format)
├── SKILL.md
└── evals/
    ├── evals.json                 ← test cases + expectations
    └── mocks.json                 ← tool call fixtures (optional)

results/                           ← output directory
├── grading.json                   ← Anthropic-native schema
├── coverage.json
├── coverage.md
├── diff.json
└── matrix.md
```

---

## Differentiation Summary

| Capability | Anthropic skill-creator v2 | OpenAI eval-skills | **SkillUnit v2** |
|---|---|---|---|
| Standalone CLI | No | No | **Yes** |
| OpenAI skill format support | No | Yes | **Yes** |
| Anthropic skill format support | Yes | No | **Yes** |
| Multi-provider (Anthropic, OpenAI, local) | No | No | **Yes** |
| Trigger + task testing coupled | No | Partial | **Yes** |
| Explicit hybrid oracle declaration | No | No | **Yes** |
| Deterministic check library | No | Partial | **Yes** |
| Mock environment | No | No | **Yes** |
| Coverage metric for skill instructions | No | No | **Yes** |
| Version diff / regression surface | No | No | **Yes** |
| Cross-model matrix | No | No | **Yes** |
| CI / GitHub Actions ready | No | Partial | **Yes** |
| Anthropic grading.json compatibility | Yes | No | **Yes** |

---

## Success Metrics

| Metric | Target |
|---|---|
| Install | `pip install skillunit` with zero non-standard dependencies |
| Format coverage | Both Anthropic and OpenAI SKILL.md formats parse correctly |
| Schema compatibility | 100% of `grading.json` files pass Anthropic's viewer unmodified |
| Deterministic checks | Zero LLM calls for expectations that match a deterministic rule |
| Coverage accuracy | Ablation correctly identifies known-dead sections in synthetic skill |
| CI readiness | Reference GitHub Actions workflow ships on day one |

---

## Summary

SkillUnit v2 is a **universal, framework-agnostic, standalone test framework** for agent skills. It occupies a gap that no existing tool fills: it runs anywhere without a parent product, supports both Anthropic and OpenAI skill formats against any provider, couples trigger testing with task testing in a single pass, and gives developers three capabilities unavailable anywhere else — a coverage metric that identifies dead instructions, a mock layer for hermetic testing of environment-dependent skills, and a diff command that surfaces regressions between skill versions.

The implementation is six focused phases over twelve weeks. Each phase ships a usable artifact. The end state is a PyPI package, a Claude Code skill, a CI workflow template, and a coverage tool that treats skill instructions as first-class software artifacts subject to the same quality standards as production code.
