"""Search providers + the whitelist filter. Nothing outside sources.yaml survives `filter_and_rank`."""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.outlets import all_outlets, outlet_for_url

log = logging.getLogger(__name__)

MAX_PER_OUTLET = 2
MAX_TOTAL = 12


@dataclass
class SearchResult:
    url: str
    title: str
    is_claimreview: bool = False
    rating: str | None = None  # ClaimReview textualRating
    outlet_id: str = ""
    # Page text supplied by the search provider: used when the outlet blocks our own fetch
    # (Reuters, AP and AFP return 401/403 to non-browser clients). Quotes are verified against it all the same.
    text: str | None = None


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    async def search(self, claim: str) -> list[SearchResult]: ...


class MockSearch(SearchProvider):
    """Returns fixture sources whose `claim_keys` all appear in the claim."""
    name = "mock"

    def __init__(self, fixtures_dir: Path) -> None:
        self.sources = [json.loads(f.read_text()) for f in sorted((fixtures_dir / "sources").glob("*.json"))]

    async def search(self, claim: str) -> list[SearchResult]:
        claim_l = claim.lower()
        return [
            SearchResult(url=s["url"], title=s["title"], is_claimreview=bool(s.get("claimreview_rating")),
                         rating=s.get("claimreview_rating"))
            for s in self.sources
            if s.get("claim_keys") and all(k in claim_l for k in s["claim_keys"])
        ]


class GoogleFactCheckSearch(SearchProvider):
    name = "google_factcheck"
    URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, claim: str) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(self.URL, params={"query": claim[:300], "languageCode": "en",
                                                   "pageSize": 20, "key": self.api_key})
            r.raise_for_status()
        results = []
        for c in r.json().get("claims", []):
            for review in c.get("claimReview", []):
                url = review.get("url", "")
                site = (review.get("publisher") or {}).get("site", "")
                # Keep only ClaimReviews whose review URL (or publisher site) is a whitelisted outlet.
                if not (outlet_for_url(url) or (site and outlet_for_url(f"https://{site}"))):
                    continue
                results.append(SearchResult(url=url, title=review.get("title") or c.get("text", "")[:120],
                                            is_claimreview=True, rating=review.get("textualRating")))
        return results


class TavilySearch(SearchProvider):
    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, claim: str) -> list[SearchResult]:
        domains = [d for o in all_outlets() for d in o.domains]
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(self.URL, headers={"Authorization": f"Bearer {self.api_key}"},
                                  json={"query": claim[:300], "include_domains": domains,
                                        "max_results": 15, "search_depth": "basic", "include_raw_content": True})
            r.raise_for_status()
        return [SearchResult(url=x["url"], title=x.get("title", ""),
                             text=x.get("raw_content") or x.get("content") or None)
                for x in r.json().get("results", [])]


class BraveSearch(SearchProvider):
    name = "brave"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, claim: str) -> list[SearchResult]:
        sites = " OR ".join(f"site:{d}" for o in all_outlets() for d in o.domains)
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(self.URL, headers={"X-Subscription-Token": self.api_key,
                                                    "Accept": "application/json"},
                                 params={"q": f"{claim[:250]} ({sites})", "count": 20, "extra_snippets": "true"})
            r.raise_for_status()
        return [SearchResult(url=x["url"], title=x.get("title", ""),
                             text=" ".join([x.get("description", ""), *x.get("extra_snippets", [])]).strip() or None)
                for x in r.json().get("web", {}).get("results", [])]


class CompositeSearch(SearchProvider):
    """Google Fact Check first, then web search. A failing provider is skipped, not fatal."""
    name = "composite"

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers
        self.name = "+".join(p.name for p in providers) or "none"

    async def search(self, claim: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        for batch in await asyncio.gather(*(p.search(claim) for p in self.providers), return_exceptions=True):
            if isinstance(batch, BaseException):
                log.warning("search provider failed: %s", type(batch).__name__)
                continue
            out.extend(batch)
        return out


def filter_and_rank(results: list[SearchResult]) -> list[SearchResult]:
    """Drop non-whitelisted and duplicate URLs; keep ≤2 per outlet (ClaimReviews, then path_hint) and ≤12 total."""
    seen: set[str] = set()
    by_outlet: dict[str, list[SearchResult]] = {}
    for r in results:
        outlet = outlet_for_url(r.url)
        key = r.url.split("#")[0].rstrip("/")
        if outlet is None or key in seen:
            continue
        seen.add(key)
        r.outlet_id = outlet.id
        by_outlet.setdefault(outlet.id, []).append(r)

    picked: list[SearchResult] = []
    for outlet in all_outlets():
        items = by_outlet.get(outlet.id, [])
        items.sort(key=lambda r: (not r.is_claimreview,
                                  not (outlet.path_hint and outlet.path_hint in r.url)))
        picked.extend(items[:MAX_PER_OUTLET])
    return picked[:MAX_TOTAL]


def make_search(settings: Settings) -> SearchProvider:
    if settings.search_provider == "mock":
        return MockSearch(settings.fixtures_dir)
    providers: list[SearchProvider] = []
    if settings.google_factcheck_api_key:
        providers.append(GoogleFactCheckSearch(settings.google_factcheck_api_key))
    if settings.search_provider == "tavily" and settings.tavily_api_key:
        providers.append(TavilySearch(settings.tavily_api_key))
    if settings.search_provider == "brave" and settings.brave_api_key:
        providers.append(BraveSearch(settings.brave_api_key))
    if not providers:
        log.warning("no search API keys set: every check will come back unverified")
    return CompositeSearch(providers)
