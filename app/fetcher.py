"""Fetch source pages and extract their main text."""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx
import trafilatura

log = logging.getLogger(__name__)

PER_URL_TIMEOUT = 5.0
TOTAL_BUDGET = 12.0
MAX_SOURCE_CHARS = 12000  # keep LLM inputs small: resource use
USER_AGENT = "Mozilla/5.0 (compatible; FactCheckCoach/0.1; +https://github.com/)"


class Fetcher(ABC):
    @abstractmethod
    async def fetch_all(self, urls: list[str]) -> dict[str, str]:
        """Return {url: text} for the URLs that could be fetched. Failures are skipped."""


class HttpFetcher(Fetcher):
    async def _fetch(self, client: httpx.AsyncClient, url: str) -> tuple[str, str | None]:
        try:
            r = await client.get(url)
            r.raise_for_status()
            text = await asyncio.to_thread(trafilatura.extract, r.text, include_comments=False)
            return url, (text or "")[:MAX_SOURCE_CHARS] or None
        except Exception as e:  # any single-source failure is skipped
            log.info("fetch failed for %s: %s", httpx.URL(url).host, type(e).__name__)
            return url, None

    async def fetch_all(self, urls: list[str]) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=PER_URL_TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as client:
            tasks = [asyncio.create_task(self._fetch(client, u)) for u in urls]
            done, pending = await asyncio.wait(tasks, timeout=TOTAL_BUDGET) if tasks else (set(), set())
            for t in pending:
                t.cancel()
        return {url: text for url, text in (t.result() for t in done) if text}


class FixtureFetcher(Fetcher):
    """Serves saved source pages from tests/fixtures/sources. Records what was fetched."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.pages = {}
        for f in sorted((fixtures_dir / "sources").glob("*.json")):
            src = json.loads(f.read_text())
            self.pages[src["url"]] = src["text"]
        self.fetched: list[str] = []

    async def fetch_all(self, urls: list[str]) -> dict[str, str]:
        self.fetched.extend(urls)
        return {u: self.pages[u] for u in urls if u in self.pages}
