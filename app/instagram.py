"""Instagram links: detect them and read the public caption preview, best effort.

We only read the og: meta tags of the public post page. No login, no scraping library,
no comments, no profile. Username and like/comment counts are dropped immediately.
"""
import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

import httpx

log = logging.getLogger(__name__)

TIMEOUT = 4.0
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
IG_URL_RE = re.compile(
    r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(p|reel|reels|tv)/([\w-]+)", re.I)
META_RE = re.compile(r'<meta\s+[^>]*property="og:(description|title)"\s+content="([^"]*)"', re.I)
# "1,204 likes, 88 comments - some.user on March 3, 2019: "caption"."
DESC_RE = re.compile(
    r'^(?:.*?-\s+)?[\w.]+\s+on\s+(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4}):\s*"(?P<cap>.*)"\s*\.?\s*$', re.S)
# "Some Name on Instagram: "caption""
TITLE_RE = re.compile(r'^.*?\bon Instagram:\s*"(?P<cap>.*)"\s*$', re.S)

NEEDS_TEXT_MSG = ("Instagram didn't let me read that post. Paste the caption (or what the Reel says) "
                  "and I'll check it.")
HASHTAGS_ONLY_MSG = "That caption is only hashtags. Type what the post or Reel claims and I'll check it."


@dataclass
class CaptionResult:
    caption: str | None
    post_date: date | None
    is_reel: bool


def find_instagram_url(*candidates: str | None) -> str | None:
    for c in candidates:
        if c and (m := IG_URL_RE.search(c)):
            return m.group(0)
    return None


def is_reel_url(url: str) -> bool:
    m = IG_URL_RE.search(url)
    return bool(m and m.group(1).lower() in ("reel", "reels", "tv"))


def parse_og(page: str) -> tuple[str | None, date | None]:
    """Return (caption, post_date) from og: tags, with username and counts stripped."""
    tags = {k.lower(): html.unescape(v) for k, v in META_RE.findall(page)}
    if (desc := tags.get("description")) and (m := DESC_RE.match(desc.strip())):
        try:
            posted = datetime.strptime(m.group("date"), "%B %d, %Y").date()
        except ValueError:
            posted = None
        return m.group("cap").strip() or None, posted
    if (title := tags.get("title")) and (m := TITLE_RE.match(title.strip())):
        return m.group("cap").strip() or None, None
    return None, None


async def get_caption(url: str, client: httpx.AsyncClient | None = None) -> CaptionResult:
    reel = is_reel_url(url)
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                         headers={"User-Agent": BROWSER_UA})
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return CaptionResult(None, None, reel)
        caption, posted = parse_og(r.text)
        return CaptionResult(caption, posted, reel)
    except httpx.HTTPError as e:
        log.info("instagram fetch failed: %s", type(e).__name__)
        return CaptionResult(None, None, reel)
    finally:
        if own:
            await client.aclose()
