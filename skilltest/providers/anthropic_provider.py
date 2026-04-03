import anthropic
from skilltest.providers.base import SkillTestProvider

class AnthropicProvider:
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self._model = model
        self._client = anthropic.Anthropic()

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
