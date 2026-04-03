import threading
import time
from skilltest.models import CanonicalSkill, ExecutionMetrics, TestConstraints
from skilltest.providers.base import SkillTestProvider


def build_system_prompt_from_body(name: str, body: str) -> str:
    return (
        f"You are Claude. The following skill is active for this session.\n"
        f"Read it carefully and follow its instructions exactly when responding.\n\n"
        f"=== SKILL: {name} ===\n{body}\n=== END SKILL ===\n\n"
        f"Execute the user's request by following the skill's instructions."
    )


def run_task(
    skill: CanonicalSkill,
    prompt: str,
    provider: SkillTestProvider,
    skill_body_override: str | None = None,
    constraints: TestConstraints | None = None,
) -> tuple[str, ExecutionMetrics]:
    body = skill_body_override if skill_body_override is not None else skill.body
    system = build_system_prompt_from_body(skill.name, body)
    timeout = constraints.timeout_seconds if constraints else None

    t0 = time.perf_counter()

    if timeout is not None:
        result_holder: list[str | None] = [None]
        error_holder: list[BaseException | None] = [None]

        def _call() -> None:
            try:
                result_holder[0] = provider.complete(system=system, user=prompt, max_tokens=2048)
            except BaseException as exc:  # noqa: BLE001
                error_holder[0] = exc

        thread = threading.Thread(target=_call, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            elapsed = time.perf_counter() - t0
            metrics = ExecutionMetrics(
                output_chars=0,
                transcript_chars=len(prompt),
                duration_seconds=round(elapsed, 3),
                errors_encountered=1,
            )
            return f"[TIMEOUT: agent exceeded {timeout}s limit]", metrics

        if error_holder[0] is not None:
            raise error_holder[0]

        output = result_holder[0] or ""
    else:
        output = provider.complete(system=system, user=prompt, max_tokens=2048)

    elapsed = time.perf_counter() - t0

    metrics = ExecutionMetrics(
        output_chars=len(output),
        transcript_chars=len(prompt) + len(output),
        duration_seconds=round(elapsed, 3),
    )
    return output, metrics
