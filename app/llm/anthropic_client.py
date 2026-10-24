"""Anthropic Claude fallback provider (small, fast model)."""
import anthropic

from app.llm.base import LLMClient, LLMError


class AnthropicLLM(LLMClient):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__()
        self.model = model
        # api_key may be empty: the SDK then resolves credentials from its own env/profile chain.
        self.client = anthropic.AsyncAnthropic(api_key=api_key or None, timeout=20.0, max_retries=1)

    async def _complete(self, task: str, system: str, user: str) -> str:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low"},  # narrow reading tasks don't need deep thinking
            )
        except anthropic.APIConnectionError as e:
            raise LLMError("anthropic connection failed") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic returned {e.status_code}") from e
        if response.stop_reason == "refusal":
            raise LLMError("anthropic declined the request")
        return "".join(b.text for b in response.content if b.type == "text")
