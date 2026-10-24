import base64
import dataclasses
import json
import logging

import httpx
import pytest
import respx

from app.vision import (IcaVision, ImageError, decode_image, image_host_allowed, scrub_ui, sniff_mime)
from tests.conftest import FIXTURES

HEADLINE = (FIXTURES / "images" / "headline_5g.png").read_bytes()
B64 = base64.b64encode(HEADLINE).decode()


def test_scrub_removes_usernames_and_counts_but_keeps_short_comments():
    raw = "dailyworldnews_official\n@someone\nBREAKING NEWS\n♥ 12,408 likes\nView all 1,233 comments\n3 replies\nfake\nReply"
    assert scrub_ui(raw) == "BREAKING NEWS\nfake"


def test_sniff_and_decode():
    assert sniff_mime(HEADLINE) == "image/png"
    assert decode_image(f"data:image/png;base64,{B64}") == HEADLINE
    with pytest.raises(ImageError):
        decode_image(base64.b64encode(b"not an image").decode())


def test_image_url_allowlist():
    assert image_host_allowed("https://scontent-ams2-1.cdninstagram.com/v/t51/abc.jpg")
    assert image_host_allowed("https://scontent.xx.fbcdn.net/x.jpg")
    assert not image_host_allowed("http://scontent.cdninstagram.com/x.jpg")  # https only
    assert not image_host_allowed("https://cdninstagram.com.evil.io/x.jpg")
    assert not image_host_allowed("https://169.254.169.254/latest/meta-data")


async def test_screenshot_only_post_is_checked(pipeline):
    out = await pipeline.run("", image=HEADLINE)
    assert out.evidence.verdict == "false"
    assert out.signals.image_mentioned
    assert out.question.startswith("It's a screenshot.")
    assert pipeline.stats["images_read"] == 1


async def test_image_without_text_asks_for_text(pipeline):
    blank = (FIXTURES / "images" / "comments_5g.png").read_bytes()[:-1] + b"\x00"  # unknown to the mock
    out = await pipeline.run("", image=blank)
    assert out.needs_text and "reverse image search" in out.note


def test_api_accepts_screenshot(client):
    start = client.post("/check/start", json={"image_base64": B64, "client": "telegram"}).json()
    assert start["checkable"] and start["check_id"]
    reveal = client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "true"}).json()
    assert reveal["verdict"] == "false"


def test_api_rejects_non_image(client):
    r = client.post("/check/start", json={"image_base64": base64.b64encode(b"hello").decode()})
    assert r.status_code == 422


def test_screenshot_is_not_stored_or_logged(client, pipeline, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/check/start", json={"image_base64": B64})
    stored = json.dumps([dataclasses.asdict(v) for v in pipeline.claim_cache.values()], default=str)
    for blob in (stored, caplog.text):
        assert "Daily World Herald" not in blob and B64[:200] not in blob


@respx.mock
async def test_ica_vision_sends_image_and_scrubs_ui():
    route = respx.post("https://api.servicesessentials.ibm.com/v1/chat-models/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "dailyworldnews_official\nScientists confirm that 5G towers make people sick\n♥ 12,408 likes"}}]}))
    text = await IcaVision("sk-test", "https://api.servicesessentials.ibm.com/v1", "vision-model").transcribe(HEADLINE)
    assert text == "Scientists confirm that 5G towers make people sick"
    body = json.loads(route.calls[0].request.content)
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@respx.mock
async def test_ica_vision_no_text_and_failure_return_none():
    url = "https://api.servicesessentials.ibm.com/v1/chat-models/chat/completions"
    respx.post(url).mock(side_effect=[httpx.Response(200, json={"choices": [{"message": {"content": "NO_TEXT"}}]}),
                                      httpx.Response(500)])
    v = IcaVision("sk-test", "https://api.servicesessentials.ibm.com/v1", "m")
    assert await v.transcribe(HEADLINE) is None
    assert await v.transcribe(HEADLINE) is None
