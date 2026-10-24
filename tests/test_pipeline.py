from tests.conftest import FIXTURES, ScriptedLLM, post


async def test_false_viral_caption(pipeline):
    out = await pipeline.run(post("false_5g")["caption"])
    ev = out.evidence
    assert (ev.verdict, ev.confidence) == ("false", "high")
    assert ev.agreement.contradicts == 4
    assert ev.agreement.supports == 0
    assert ev.agreement.outlets_checked == 6
    assert all(s.stance == "contradicts" for s in ev.sources)
    assert ev.sources[0].is_claimreview  # ClaimReview shown first
    assert out.question and "link in bio" in out.question


async def test_hallucinated_quote_is_rejected_and_counted(pipeline):
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    assert ev.agreement.rejected_quotes == 1
    assert not any(s.domain == "politifact.com" for s in ev.sources)
    assert pipeline.stats["rejected_quotes"] == 1


async def test_non_whitelisted_result_is_never_fetched(pipeline):
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    assert not any("dailytruth" in u for u in pipeline.fetcher.fetched)
    assert not any("dailytruth" in s.url for s in ev.sources)


async def test_true_claim_from_headline_screenshot(pipeline):
    out = await pipeline.run(post("true_eiffel")["caption"])
    assert (out.evidence.verdict, out.evidence.confidence) == ("true", "high")
    assert "screenshot" in out.question.lower()
    assert out.tip.startswith("Find the original")


async def test_opinion(pipeline):
    out = await pipeline.run(post("opinion_pizza")["caption"])
    assert out.evidence.verdict == "opinion"
    assert out.evidence.checkable is False
    assert out.question is None and out.note


async def test_breaking_reel_with_no_coverage_is_developing(pipeline):
    p = post("breaking_reel")
    out = await pipeline.run(p["caption"], "https://www.instagram.com/reel/FIXREEL01/")
    assert out.evidence.verdict == "developing"
    assert out.evidence.sources == []
    assert "Reel" in out.question


async def test_instagram_url_only_reads_caption_from_og_tags(pipeline):
    out = await pipeline.run("", post("false_5g")["url"])
    assert out.evidence.verdict == "false"
    assert out.signals.old_date and out.signals.old_year == 2019
    assert out.tip.startswith("Check the date: this is from 2019")


async def test_blocked_instagram_link_asks_for_text(pipeline):
    out = await pipeline.run("", "https://www.instagram.com/p/UNKNOWN123/")
    assert out.needs_text and "screenshot" in out.note and "paste the caption" in out.note


async def test_hashtags_only_caption_asks_for_text(pipeline):
    out = await pipeline.run("#news #breaking #viral")
    assert out.needs_text


async def test_extraction_failure_falls_back_to_unverified(pipeline):
    pipeline.llm = ScriptedLLM(["not json at all", "still not json"])
    out = await pipeline.run("Some random statement about the moon being made of cheese.")
    assert out.evidence.verdict == "unverified"
    assert pipeline.llm.calls["extract_claim"] == 2


async def test_blocked_fetch_falls_back_to_search_provider_text(pipeline):
    from app.search import SearchResult

    class BlockedOutletSearch:
        name = "blocked"

        async def search(self, claim):
            text = "Fact check. There is no evidence that 5G networks make people sick, experts say."
            return [SearchResult("https://www.reuters.com/fact-check/live-only/", "R", text=text),
                    SearchResult("https://apnews.com/article/live-only", "A", text=text)]

    class StanceFromText(type(pipeline.llm)):
        async def _complete(self, task, system, user):
            if task == "stance":
                return '{"stance": "contradicts", "quote": "There is no evidence that 5G networks make people sick"}'
            return await super()._complete(task, system, user)

    pipeline.search = BlockedOutletSearch()
    pipeline.llm = StanceFromText(FIXTURES)
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    assert ev.verdict == "false" and ev.agreement.contradicts == 2 and ev.agreement.rejected_quotes == 0


async def test_unreachable_claimreview_is_read_from_its_structured_data(pipeline):
    from app.search import SearchResult

    class ClaimReviewOnly:
        name = "cr-only"

        async def search(self, claim):
            return [SearchResult("https://www.reuters.com/fact-check/unreachable/", "R", is_claimreview=True,
                                 rating="False", reviewed_claim="5G towers make people sick")]

    class Labeller(type(pipeline.llm)):
        async def _complete(self, task, system, user):
            if task == "stance":
                assert 'Claim reviewed: "5G towers make people sick". Rating: False.' in user
                return '{"stance": "contradicts", "quote": "Claim reviewed: \\"5G towers make people sick\\". Rating: False."}'
            return await super()._complete(task, system, user)

    pipeline.search = ClaimReviewOnly()
    pipeline.llm = Labeller(FIXTURES)
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    assert (ev.verdict, ev.agreement.contradicts) == ("false", 1)
    assert ev.sources[0].rating == "False" and ev.sources[0].is_claimreview


def test_explanation_guard_blocks_links_markdown_and_new_numbers():
    from app.stance import explanation_is_safe
    quotes = ["An estimated 1,500 shops and businesses were looted and destroyed."]
    assert explanation_is_safe("About 1,500 shops were looted, according to the outlets.", quotes)
    assert not explanation_is_safe("![chart](https://example.com/c.png) Shops were looted.", quotes)
    assert not explanation_is_safe("See www.example.com for more.", quotes)
    assert not explanation_is_safe("Over 3,000 shops were looted.", quotes)          # number not in quotes
    assert not explanation_is_safe("**Shops** were looted.", quotes)


async def test_explanation_with_invented_link_falls_back_to_template(pipeline):
    class LinkyLLM(type(pipeline.llm)):
        async def _complete(self, task, system, user):
            if task == "explain":
                return "![Looted](https://example.com/chart.png) It is false."
            return await super()._complete(task, system, user)
    pipeline.llm = LinkyLLM(FIXTURES)
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    assert "http" not in ev.explanation and ev.explanation.startswith("4 of the 4 trusted outlets")
