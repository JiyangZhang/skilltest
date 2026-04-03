#!/usr/bin/env bash
# SkillTest agent container: reads /workspace/prompt.txt, writes /workspace/output/stdout.txt
set -eu -o pipefail

mkdir -p /workspace/output/artifacts

PROMPT_FILE=/workspace/prompt.txt
OUT=/workspace/output/stdout.txt

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Missing /workspace/prompt.txt" | tee "$OUT"
  exit 1
fi

if [[ -n "${CLAUDE_CODE_INVOCATION:-}" ]]; then
  bash -c "$CLAUDE_CODE_INVOCATION" 2>&1 | tee "$OUT"
  exit "${PIPESTATUS[0]}"
fi

if command -v claude >/dev/null 2>&1; then
  # Build args array — no eval, so prompt text with spaces/quotes is safe
  CLAUDE_ARGS=(-p "$(cat "$PROMPT_FILE")" --dangerously-skip-permissions)
  if [[ -n "${CLAUDE_CODE_MODEL:-}" ]]; then
    CLAUDE_ARGS+=(--model "$CLAUDE_CODE_MODEL")
  fi
  if [[ -n "${CLAUDE_CODE_ARGS:-}" ]]; then
    # CLAUDE_CODE_ARGS is a simple flag string like "--max-turns 5"; split on whitespace
    read -ra _extra <<< "${CLAUDE_CODE_ARGS}"
    CLAUDE_ARGS+=("${_extra[@]}")
  fi
  claude "${CLAUDE_ARGS[@]}" 2>&1 | tee "$OUT"
  exit "${PIPESTATUS[0]}"
fi

msg="skilltest: Claude Code CLI ('claude') not found in this image. Install the official CLI, set CLAUDE_CODE_INVOCATION, or on the host use: skilltest run --pytest-only (pytest-only; no agent)."
echo "$msg" | tee "$OUT"
exit 1
