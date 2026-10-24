"""IBM watsonx.ai (Granite) via the REST chat endpoint."""
import time

import httpx

from app.llm.base import LLMClient, LLMError

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
API_VERSION = "2024-10-08"


class WatsonxLLM(LLMClient):
    name = "watsonx"

    def __init__(self, api_key: str, project_id: str, base_url: str, model_id: str) -> None:
        super().__init__()
        if not api_key or not project_id:
            raise LLMError("WATSONX_API_KEY and WATSONX_PROJECT_ID are required")
        self.api_key = api_key
        self.project_id = project_id
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self._token: str | None = None
        self._token_expiry = 0.0

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = await client.post(
            IAM_URL,
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": self.api_key},
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 3600))
        return self._token

    async def _complete(self, task: str, system: str, user: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token = await self._get_token(client)
                r = await client.post(
                    f"{self.base_url}/ml/v1/text/chat",
                    params={"version": API_VERSION},
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "model_id": self.model_id,
                        "project_id": self.project_id,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": 400,
                        "temperature": 0,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"watsonx call failed: {type(e).__name__}") from e
