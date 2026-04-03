"""Standard layout for a single agent run (host or Docker mount at /workspace)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

# Paths are relative to the run root (e.g. .../runs/test-1/)
OUTPUT_DIR = "output"
STDOUT_REL = Path("output") / "stdout.txt"
ARTIFACTS_REL = Path("output") / "artifacts"
PROMPT_REL = Path("prompt.txt")
INPUT_REL = Path("input")
MANIFEST_REL = Path("output") / "manifest.json"


@dataclass
class RunBundle:
    """Materialized run directory on the host after Docker exits."""

    run_root: Path
    stdout_text: str
    artifacts_dir: Path


def ensure_output_dirs(run_root: Path) -> None:
    (run_root / OUTPUT_DIR / "artifacts").mkdir(parents=True, exist_ok=True)


def prepare_run_directory(
    run_root: Path,
    *,
    prompt_text: str,
    input_src: Path | None,
) -> None:
    """Create run_root with prompt.txt, input/, and empty output tree."""
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / PROMPT_REL).write_text(prompt_text, encoding="utf-8")
    dest_input = run_root / INPUT_REL
    if dest_input.exists():
        shutil.rmtree(dest_input)
    if input_src is not None and input_src.exists():
        shutil.copytree(input_src, dest_input)
    else:
        dest_input.mkdir(parents=True, exist_ok=True)
    ensure_output_dirs(run_root)


def read_run_bundle(run_root: Path) -> RunBundle:
    """Load stdout and artifacts path; stdout file must exist after a successful run."""
    stdout_path = run_root / STDOUT_REL
    if not stdout_path.is_file():
        raise FileNotFoundError(
            f"Expected agent stdout at {stdout_path}. "
            "Ensure the Docker entrypoint or Claude Code run wrote output/stdout.txt."
        )
    text = stdout_path.read_text(encoding="utf-8")
    artifacts = run_root / ARTIFACTS_REL
    if not artifacts.is_dir():
        artifacts.mkdir(parents=True, exist_ok=True)
    return RunBundle(run_root=run_root, stdout_text=text, artifacts_dir=artifacts)


def write_manifest(
    run_root: Path,
    *,
    test_id: int,
    exit_code: int,
    docker_image: str | None = None,
) -> None:
    path = run_root / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "test_id": test_id,
        "exit_code": exit_code,
        "docker_image": docker_image,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def summarize_artifacts_for_judge(
    artifacts_dir: Path,
    *,
    max_files: int = 12,
    max_chars_per_file: int = 4000,
) -> str:
    """Build a bounded text block listing artifact files and small-file contents."""
    if not artifacts_dir.is_dir():
        return "(no artifacts directory)"
    files: list[Path] = []
    for p in sorted(artifacts_dir.rglob("*")):
        if p.is_file():
            files.append(p)
    if not files:
        return "(artifacts/ is empty)"
    lines: list[str] = ["--- Artifact files (relative to artifacts/) ---"]
    shown = 0
    for p in files:
        if shown >= max_files:
            lines.append(f"... and {len(files) - max_files} more file(s)")
            break
        rel = p.relative_to(artifacts_dir)
        lines.append(f"- {rel.as_posix()} ({p.stat().st_size} bytes)")
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            shown += 1
            continue
        snippet = raw[:max_chars_per_file]
        if len(raw) > max_chars_per_file:
            snippet += "\n... [truncated]"
        lines.append(f"  Content:\n{snippet}")
        shown += 1
    return "\n".join(lines)
