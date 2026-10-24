"""Official Instagram Graph API (Instagram API with Instagram Login) for OUR demo account only.

Reads captions, images and comments of the account's own posts with its access token. Never logs in
with a password, never touches other accounts. Comment usernames are never requested.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.instagram import IG_URL_RE

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.instagram.com/v23.0"
MAX_MEDIA_PAGES = 4    # 4 × 50 most recent posts is plenty for a demo account
MAX_COMMENTS = 50


@dataclass
class OwnPost:
    id: str
    caption: str | None
    image_url: str | None
    post_date: date | None
    is_reel: bool


def shortcode_of(url: str) -> str | None:
    m = IG_URL_RE.search(url or "")
    return m.group(2) if m else None


class InstagramGraph:
    def __init__(self, access_token: str, user_id: str, base_url: str = GRAPH_URL) -> None:
        self.token, self.user_id, self.base_url = access_token, user_id, base_url.rstrip("/")

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
        r = await client.get(url, params={**(params or {}), "access_token": self.token})
        r.raise_for_status()
        return r.json()

    async def find_post(self, url: str) -> OwnPost | None:
        """The demo account's post with this link, or None (not ours, or the API failed)."""
        code = shortcode_of(url)
        if not code:
            return None
        fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                page = await self._get(client, f"{self.base_url}/{self.user_id}/media", {"fields": fields, "limit": 50})
                for _ in range(MAX_MEDIA_PAGES):
                    for m in page.get("data", []):
                        if shortcode_of(m.get("permalink", "")) == code:
                            return self._post(m)
                    nxt = page.get("paging", {}).get("next")
                    if not nxt:
                        break
                    page = (await client.get(nxt)).json()  # `next` already carries the token
        except (httpx.HTTPError, ValueError) as e:
            log.warning("instagram graph lookup failed: %s", type(e).__name__)
        return None

    @staticmethod
    def _post(m: dict) -> OwnPost:
        try:
            posted = datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).date()
        except (KeyError, ValueError):
            posted = None
        video = m.get("media_type") == "VIDEO"
        return OwnPost(id=m["id"], caption=m.get("caption"), post_date=posted, is_reel=video,
                       image_url=m.get("thumbnail_url") if video else m.get("media_url"))

    async def comments(self, media_id: str) -> list[str]:
        """Comment texts only (no usernames), newest first, up to MAX_COMMENTS."""
        texts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                page = await self._get(client, f"{self.base_url}/{media_id}/comments", {"fields": "text", "limit": 50})
                while True:
                    texts += [c["text"].strip() for c in page.get("data", []) if c.get("text", "").strip()]
                    nxt = page.get("paging", {}).get("next")
                    if not nxt or len(texts) >= MAX_COMMENTS:
                        break
                    page = (await client.get(nxt)).json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("instagram graph comments failed: %s", type(e).__name__)
        return texts[:MAX_COMMENTS]
