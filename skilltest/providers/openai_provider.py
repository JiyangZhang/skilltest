from openai import OpenAI
from skilltest.providers.base import SkillTestProvider

class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o"):
        self._model = model
        self._client = OpenAI()

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
