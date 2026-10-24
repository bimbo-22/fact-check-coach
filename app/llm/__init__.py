from app.config import Settings
from app.llm.base import LLMClient, LLMError


def make_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "ollama":
        from app.llm.ollama import OllamaLLM

        return OllamaLLM(settings.ollama_url, settings.ollama_model)
    if settings.llm_provider == "watsonx":
        from app.llm.watsonx import WatsonxLLM

        return WatsonxLLM(settings.watsonx_api_key, settings.watsonx_project_id,
                          settings.watsonx_url, settings.watsonx_model_id)
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model)
    from app.llm.mock import MockLLM

    return MockLLM(settings.fixtures_dir)


__all__ = ["LLMClient", "LLMError", "make_llm"]
