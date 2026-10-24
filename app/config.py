"""Settings loaded from the environment / .env file."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["mock", "watsonx", "anthropic"] = "mock"
    # google_factcheck = ClaimReviews only; tavily / brave = ClaimReviews (if key set) + web search
    search_provider: Literal["mock", "google_factcheck", "tavily", "brave"] = "mock"

    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_model_id: str = "ibm/granite-3-8b-instruct"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"

    google_factcheck_api_key: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""

    telegram_bot_token: str = ""
    api_base_url: str = "http://localhost:8000"

    check_ttl_seconds: int = 15 * 60
    cache_ttl_seconds: int = 6 * 60 * 60
    max_input_chars: int = 2000
    fixtures_dir: Path = FIXTURES_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()
