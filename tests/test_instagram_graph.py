from datetime import date

import httpx
import respx

from app.instagram_graph import GRAPH_URL, InstagramGraph
from tests.conftest import post

MEDIA = f"{GRAPH_URL}/1789/media"
POST_URL = "https://www.instagram.com/p/OURPOST1/"


def media_page():
    return httpx.Response(200, json={"data": [
        {"id": "m1", "caption": "Old post", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/a.jpg",
         "permalink": "https://www.instagram.com/p/OTHER1/", "timestamp": "2026-10-01T10:00:00+0000"},
        {"id": "m2", "caption": post("false_5g")["caption"], "media_type": "IMAGE",
         "media_url": "https://scontent.cdninstagram.com/b.jpg", "permalink": POST_URL,
         "timestamp": "2019-03-03T10:00:00+0000"}]})


@respx.mock
async def test_find_own_post_by_link():
    route = respx.get(MEDIA).mock(return_value=media_page())
    p = await InstagramGraph("tok", "1789").find_post("https://instagram.com/p/OURPOST1/?igsh=abc")
    assert p.id == "m2" and p.post_date == date(2019, 3, 3) and p.image_url.endswith("b.jpg")
    assert route.calls[0].request.url.params["access_token"] == "tok"


@respx.mock
async def test_other_peoples_posts_are_not_found():
    respx.get(MEDIA).mock(return_value=media_page())
    assert await InstagramGraph("tok", "1789").find_post("https://www.instagram.com/p/SOMEONEELSE/") is None


@respx.mock
async def test_comments_never_request_usernames():
    route = respx.get(f"{GRAPH_URL}/m2/comments").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "c1", "text": "5G towers make people sick"}, {"id": "c2", "text": "Is this real??"}]}))
    texts = await InstagramGraph("tok", "1789").comments("m2")
    assert texts == ["5G towers make people sick", "Is this real??"]
    assert route.calls[0].request.url.params["fields"] == "text"


@respx.mock
async def test_api_failure_is_not_fatal():
    respx.get(MEDIA).mock(return_value=httpx.Response(400, json={"error": {"message": "expired token"}}))
    assert await InstagramGraph("tok", "1789").find_post(POST_URL) is None


@respx.mock
async def test_pipeline_reads_own_post_and_its_comments(pipeline):
    respx.get(MEDIA).mock(return_value=media_page())
    respx.get("https://scontent.cdninstagram.com/b.jpg").mock(return_value=httpx.Response(404))
    respx.get(f"{GRAPH_URL}/m2/comments").mock(return_value=httpx.Response(200, json={"data": [
        {"text": "5G towers make people sick, my aunt got headaches"},
        {"text": "Fake. Reuters fact-checked this: there is no evidence 5G makes people sick"},
        {"text": "Is this real??"}]}))
    pipeline.instagram_graph = InstagramGraph("tok", "1789")
    out = await pipeline.run("", POST_URL)
    assert out.evidence.verdict == "false" and out.signals.old_year == 2019
    resp = await pipeline.comments_from_post(POST_URL)
    assert (resp.summary.misinformation, resp.summary.backed, resp.summary.questions) == (1, 1, 1)


async def test_comments_from_post_without_graph_explains(pipeline):
    resp = await pipeline.comments_from_post(POST_URL)
    assert resp.comments == [] and "our own demo account" in resp.note
