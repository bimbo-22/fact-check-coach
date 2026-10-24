from datetime import date

import httpx
import pytest
import respx

from app.instagram import find_instagram_url, get_caption, is_reel_url, parse_og
from tests.conftest import FIXTURES

OG = (FIXTURES / "instagram" / "false_5g.og.html").read_text()
BLOCKED = (FIXTURES / "instagram" / "blocked_login.html").read_text()


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/p/ABC123/",
    "https://instagram.com/p/ABC123",
    "https://www.instagram.com/reel/ABC_123/?igsh=xyz",
    "https://www.instagram.com/reels/ABC-123/",
    "https://www.instagram.com/tv/ABC123/",
    "https://m.instagram.com/p/ABC123/",
    "https://www.instagram.com/some.user/p/ABC123/",
    "look at this https://www.instagram.com/p/ABC123/?utm_source=ig_web_copy_link wow",
])
def test_detects_instagram_post_urls(url):
    assert find_instagram_url(url)


@pytest.mark.parametrize("url", [
    "https://instagram.com.fake.io/p/ABC123/",
    "https://www.instagram.com/some.user/",
    "https://www.notinstagram.com/p/ABC123/",
    None,
])
def test_rejects_non_post_urls(url):
    assert find_instagram_url(url) is None


def test_reel_detection():
    assert is_reel_url("https://www.instagram.com/reel/X/")
    assert not is_reel_url("https://www.instagram.com/p/X/")


def test_parses_caption_and_date_and_strips_personal_data():
    caption, posted = parse_og(OG)
    assert caption.startswith("😱 Scientists CONFIRM that 5G towers")
    assert posted == date(2019, 3, 3)
    for personal in ("wellness.truth.daily", "Wellness Truth Daily", "1,204", "likes", "comments"):
        assert personal not in caption


def test_title_only_fallback():
    page = '<meta property="og:title" content="Someone on Instagram: &quot;The moon is hollow&quot;" />'
    assert parse_og(page) == ("The moon is hollow", None)


def test_login_wall_gives_no_caption():
    assert parse_og(BLOCKED) == (None, None)


@respx.mock
async def test_get_caption_success():
    respx.get("https://www.instagram.com/p/FCCFIX5G01/").mock(return_value=httpx.Response(200, text=OG))
    res = await get_caption("https://www.instagram.com/p/FCCFIX5G01/")
    assert res.caption and res.post_date == date(2019, 3, 3) and not res.is_reel


@respx.mock
async def test_get_caption_blocked_or_down():
    respx.get("https://www.instagram.com/p/A/").mock(return_value=httpx.Response(200, text=BLOCKED))
    respx.get("https://www.instagram.com/p/B/").mock(return_value=httpx.Response(429))
    respx.get("https://www.instagram.com/reel/C/").mock(side_effect=httpx.ConnectTimeout("slow"))
    assert (await get_caption("https://www.instagram.com/p/A/")).caption is None
    assert (await get_caption("https://www.instagram.com/p/B/")).caption is None
    res = await get_caption("https://www.instagram.com/reel/C/")
    assert res.caption is None and res.is_reel
