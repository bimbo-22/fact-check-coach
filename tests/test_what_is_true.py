from app.search import SearchResult
from tests.conftest import FIXTURES, post


async def test_false_claim_ends_with_whats_actually_true(pipeline):
    ev = (await pipeline.run(post("false_5g")["caption"])).evidence
    w = ev.what_is_true
    assert ev.verdict == "false" and w.kind == "correction" and w.heading == "What's actually true"
    assert "no evidence" in w.text.lower() and w.sources and all(s.url.startswith("https://") for s in w.sources)


async def test_unverified_with_nothing_found_says_so_plainly(pipeline):
    ev = (await pipeline.run("A huge earthquake just hit Lisbon, buildings are collapsing")).evidence
    assert ev.verdict in ("unverified", "developing")
    if ev.verdict == "unverified":
        assert ev.what_is_true.kind == "none" and "not proof" in ev.what_is_true.text


def _search_with(text):
    class OneArticle:
        name = "one"

        async def search(self, claim):
            return [SearchResult("https://www.bbc.com/news/articles/france-unrest", "France unrest", text=text)]
    return OneArticle()


def _llm_with_related(related):
    from app.llm.mock import MockLLM

    class Related(MockLLM):
        async def _complete(self, task, system, user):
            if task == "stance":
                return '{"stance": "not_mentioned", "quote": null, "related": "%s"}' % related
            return await super()._complete(task, system, user)
    return Related(FIXTURES)


ARTICLE = ("Protests continued across France on Saturday. An estimated 1,500 shops and businesses were "
           "looted and destroyed. Police made dozens of arrests in Paris, Marseille and Lille. " * 2)


async def test_unverified_shows_what_the_outlets_do_report(pipeline):
    pipeline.search = _search_with(ARTICLE)
    pipeline.llm = pipeline.stance_llm = _llm_with_related(
        "An estimated 1,500 shops and businesses were looted and destroyed.")
    ev = (await pipeline.run("Migrants looted the store of a woman who supported immigration")).evidence
    assert ev.verdict == "unverified"
    w = ev.what_is_true
    assert w.kind == "context" and w.heading == "What the outlets do report"
    assert "1,500 shops" in w.text and w.sources[0].outlet == "BBC Verify"


async def test_invented_related_sentence_is_rejected(pipeline):
    pipeline.search = _search_with(ARTICLE)
    pipeline.llm = pipeline.stance_llm = _llm_with_related("Migrants were seen looting a liberal woman's shop.")
    ev = (await pipeline.run("Migrants looted the store of a woman who supported immigration")).evidence
    assert ev.what_is_true.kind == "none" and ev.agreement.rejected_quotes == 1


def test_api_reveal_includes_what_is_true(client):
    start = client.post("/check/start", json={"text": post("false_5g")["caption"]}).json()
    body = client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "true"}).json()
    assert body["what_is_true"]["heading"] == "What's actually true" and body["what_is_true"]["sources"]


def test_misinformation_comment_gets_the_correction(client):
    from tests.test_comments import COMMENTS, by_text
    resp = client.post("/comments/check", json={"text": COMMENTS}).json()
    assert "no evidence" in by_text(resp, "5G towers make people sick")["what_is_true"].lower()
    assert by_text(resp, "Is this real")["what_is_true"] is None
