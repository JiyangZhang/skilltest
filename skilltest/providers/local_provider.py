import httpx
from skilltest.providers.base import SkillTestProvider

class LocalProvider:
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
