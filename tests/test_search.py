import httpx
import respx

from app.config import Settings
from app.search import (BraveSearch, CompositeSearch, GoogleFactCheckSearch, SearchResult, TavilySearch,
                        filter_and_rank, make_search)


@respx.mock
async def test_google_factcheck_keeps_only_whitelisted_publishers():
    respx.get(GoogleFactCheckSearch.URL).mock(return_value=httpx.Response(200, json={"claims": [{
        "text": "5G makes people sick",
        "claimReview": [
            {"publisher": {"site": "reuters.com"}, "url": "https://www.reuters.com/fact-check/a", "textualRating": "False", "title": "R"},
            {"publisher": {"site": "randomblog.net"}, "url": "https://randomblog.net/x", "textualRating": "True"},
            {"publisher": {"site": "politifact.com"}, "url": "https://www.politifact.com/factchecks/b/", "textualRating": "Pants on Fire"},
        ]}]}))
    results = await GoogleFactCheckSearch("k").search("5G makes people sick")
    assert [r.url for r in results] == ["https://www.reuters.com/fact-check/a", "https://www.politifact.com/factchecks/b/"]
    assert all(r.is_claimreview for r in results)


@respx.mock
async def test_tavily_sends_the_six_outlet_domains():
    route = respx.post(TavilySearch.URL).mock(return_value=httpx.Response(200, json={"results": [
        {"url": "https://apnews.com/article/x", "title": "AP"}]}))
    results = await TavilySearch("k").search("claim")
    sent = route.calls[0].request.content.decode()
    for d in ("reuters.com", "apnews.com", "factcheck.afp.com", "bbc.com", "bbc.co.uk", "snopes.com", "politifact.com"):
        assert d in sent
    assert results[0].url == "https://apnews.com/article/x"


@respx.mock
async def test_brave_uses_site_operators():
    route = respx.get(BraveSearch.URL).mock(return_value=httpx.Response(200, json={"web": {"results": []}}))
    await BraveSearch("k").search("claim")
    assert "site:snopes.com" in route.calls[0].request.url.params["q"]


@respx.mock
async def test_composite_survives_a_failing_provider():
    respx.get(GoogleFactCheckSearch.URL).mock(return_value=httpx.Response(500))
    respx.post(TavilySearch.URL).mock(return_value=httpx.Response(200, json={"results": [
        {"url": "https://www.bbc.com/news/x", "title": "BBC"}]}))
    results = await CompositeSearch([GoogleFactCheckSearch("k"), TavilySearch("k")]).search("claim")
    assert [r.url for r in results] == ["https://www.bbc.com/news/x"]


def test_filter_and_rank_limits_and_order():
    raw = [SearchResult(f"https://www.reuters.com/world/{i}", "r") for i in range(4)]
    raw += [SearchResult("https://www.reuters.com/fact-check/x", "r-fc")]
    raw += [SearchResult("https://www.reuters.com/world/cr", "r-cr", is_claimreview=True, rating="False")]
    raw += [SearchResult("https://evil.example/x", "e"), SearchResult("https://www.reuters.com/world/0/", "dup")]
    picked = filter_and_rank(raw)
    assert [r.title for r in picked] == ["r-cr", "r-fc"]  # ClaimReview first, then path_hint; max 2 per outlet
    assert all(r.outlet_id == "reuters" for r in picked)


def test_filter_and_rank_total_cap():
    domains = ["reuters.com", "apnews.com", "factcheck.afp.com", "bbc.com", "snopes.com", "politifact.com"]
    raw = [SearchResult(f"https://{d}/a{i}", d) for d in domains for i in range(3)]
    assert len(filter_and_rank(raw)) == 12


def test_make_search_without_keys_is_empty_not_crashing():
    s = make_search(Settings(search_provider="tavily", tavily_api_key="", google_factcheck_api_key=""))
    assert isinstance(s, CompositeSearch) and s.providers == []
