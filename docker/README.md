# SkillTest Docker image (Claude Code CLI)

`skilltest run` defaults to **Docker** execution: it mounts a prepared run directory and your skills tree, then runs the entrypoint in `entrypoint.sh`.

## Images

| File | Contents | When to use |
|---|---|---|
| `Dockerfile.claude` | Debian + Node.js + Python 3 + Claude Code CLI | Default — build this and use it as-is or extend it |
| `Dockerfile` | Debian + bash/curl only — no Claude Code CLI | Advanced: bring your own `claude` binary or use `CLAUDE_CODE_INVOCATION` |

## Layout

Inside the container, `/workspace` is the run root:

- `prompt.txt` — task prompt (written by SkillTest)
- `input/` — copied from the test case `input_dir` in the skill
- `skills/` — read-only mount of the **parent directory** of the skill under test, so the skill lives at `/workspace/skills/<your-skill>/`
- `output/stdout.txt` — primary text for grading (`SKILLTEST_OUTPUT`)
- `output/artifacts/` — extra files for pytest / LLM judge

## Build

From the repository root:

```bash
docker build -t skilltest-claude:latest -f docker/Dockerfile.claude docker/
```

Override the image name when running tests:

```bash
export SKILLTEST_DOCKER_IMAGE=my-registry/skilltest-claude:1
skilltest run ./my-skill
```

## Skill-level Dockerfiles

The default image works for any skill — the agent installs packages it needs at runtime via `pip install`. For production or CI use cases where you want deterministic, fast runs without runtime installs, place a `Dockerfile` inside the skill directory:

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

## API keys

Pass `ANTHROPIC_API_KEY` into the container (SkillTest forwards it from the host when using `docker run`).
