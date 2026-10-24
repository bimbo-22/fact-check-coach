"""IBM Consulting Advantage (ICA) Developer API: OpenAI-compatible chat completions on IBM-hosted models.

Default model is IBM Granite (ibm/granite-4-h-small). The API has no response_format, so the JSON-only
system prompts plus our tolerant parsers (and retry) do the work.
"""
import httpx

from app.llm.base import LLMClient, LLMError


class IcaLLM(LLMClient):
    name = "ica"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        super().__init__()
        if not api_key:
            raise LLMError("ICA_API_KEY is required")
        self.api_key = api_key
        self.url = f"{base_url.rstrip('/')}/chat-models/chat/completions"
        self.model = model

    async def _complete(self, task: str, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "max_tokens": 400,
        }
        if not self.model.startswith("claude-"):  # current Claude models reject sampling parameters
            body["temperature"] = 0
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"] or ""
        except httpx.HTTPStatusError as e:
            raise LLMError(f"ICA returned {e.response.status_code}") from e
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"ICA call failed: {type(e).__name__}") from e
