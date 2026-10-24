import json
import os
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.fetcher import FixtureFetcher  # noqa: E402
from app.instagram import CaptionResult, parse_og, is_reel_url  # noqa: E402
from app.llm.base import LLMClient  # noqa: E402
from app.llm.mock import MockLLM  # noqa: E402
from app.main import create_app  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.search import MockSearch  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class ScriptedLLM(LLMClient):
    """Returns the given responses in order (then repeats the last one)."""
    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        super().__init__()
        self.responses = responses

    async def _complete(self, task, system, user) -> str:
        i = min(self.total_calls - 1, len(self.responses) - 1)
        return self.responses[i]


def post(name: str) -> dict:
    return json.loads((FIXTURES / "instagram" / f"{name}.json").read_text())


async def fixture_instagram_fetch(url: str) -> CaptionResult:
    """Offline stand-in for instagram.get_caption: serves saved og: HTML by post URL."""
    for f in (FIXTURES / "instagram").glob("*.json"):
        p = json.loads(f.read_text())
        og = FIXTURES / "instagram" / f"{f.stem}.og.html"
        if p.get("url", "").rstrip("/") == url.rstrip("/") and og.exists():
            caption, posted = parse_og(og.read_text())
            return CaptionResult(caption, posted, is_reel_url(url))
    return CaptionResult(None, None, is_reel_url(url))


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_provider="mock", search_provider="mock", fixtures_dir=FIXTURES)


@pytest.fixture
def pipeline(settings) -> Pipeline:
    return Pipeline(MockLLM(FIXTURES), MockSearch(FIXTURES), FixtureFetcher(FIXTURES), settings,
                    instagram_fetch=fixture_instagram_fetch)


@pytest.fixture
def client(settings, pipeline) -> TestClient:
    return TestClient(create_app(settings, pipeline))
