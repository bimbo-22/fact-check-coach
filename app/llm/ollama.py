"""Open-source IBM Granite running locally via Ollama: no API key, no cost, and post text never leaves the machine."""
import httpx

from app.llm.base import LLMClient, LLMError

JSON_TASKS = {"extract_claim", "stance"}  # ask Ollama to constrain these outputs to valid JSON


class OllamaLLM(LLMClient):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def _complete(self, task: str, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 400},
        }
        if task in JSON_TASKS:
            body["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError) as e:
            raise LLMError(f"ollama call failed: {type(e).__name__}") from e
