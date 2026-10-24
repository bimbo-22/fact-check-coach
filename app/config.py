"""Settings loaded from the environment / .env file."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["mock", "ica", "ollama", "watsonx", "anthropic"] = "mock"
    # google_factcheck = ClaimReviews only; tavily / brave = ClaimReviews (if key set) + web search
    search_provider: Literal["mock", "google_factcheck", "tavily", "brave"] = "mock"

    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_model_id: str = "ibm/granite-3-8b-instruct"

    # IBM Consulting Advantage Developer API (OpenAI-compatible, IBM-hosted models incl. Granite)
    ica_api_key: str = ""
    ica_base_url: str = "https://api.servicesessentials.ibm.com/v1"
    ica_model: str = "ibm/granite-4-h-small"

    # Screenshot reading. auto = same service as LLM_PROVIDER (ica/ollama), else offline mock.
    vision_provider: Literal["auto", "mock", "ica", "ollama"] = "auto"
    ica_vision_model: str = "meta-llama/llama-4-maverick-17b-128e-instruct-fp8"  # open weights
    ollama_vision_model: str = "qwen2.5vl:7b"

    # Open-source Granite on this machine (ollama pull granite4.1:8b)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "granite4.1:8b"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"

    # Official Instagram Graph API for OUR demo account (see credentials.md). Never a password.
    instagram_access_token: str = ""
    instagram_user_id: str = ""

    google_factcheck_api_key: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""  # shown on the landing page, e.g. beyond_insta_bot
    api_base_url: str = "http://localhost:8000"

    check_ttl_seconds: int = 15 * 60
    cache_ttl_seconds: int = 6 * 60 * 60
    max_input_chars: int = 2000
    fixtures_dir: Path = FIXTURES_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()
