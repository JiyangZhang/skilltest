from skilltest.providers.anthropic_provider import AnthropicProvider
from skilltest.providers.openai_provider import OpenAIProvider
from skilltest.providers.local_provider import LocalProvider
from skilltest.providers.base import SkillTestProvider


# Oracle type values (strings) that never make LLM calls during grading.
OFFLINE_ORACLE_VALUES = {"pytest"}


def make_provider(provider_str: str, model: str | None = None) -> SkillTestProvider:
    parts = provider_str.split(":", 1)
    name = parts[0].lower()
    model_override = parts[1] if len(parts) > 1 else model

    if name == "anthropic":
        return AnthropicProvider(model=model_override or "claude-haiku-4-5-20251001")
    elif name == "openai":
        return OpenAIProvider(model=model_override or "gpt-4o")
    elif name == "local":
        return LocalProvider(model=model_override or "llama3")
    else:
        raise ValueError(f"Unknown provider: '{name}'. Choose: anthropic, openai, local")
