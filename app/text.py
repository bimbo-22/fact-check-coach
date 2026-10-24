"""Input normalisation and the coaching signals we read from a post before discarding it.

Signals are booleans only, so nothing from the post is kept after the request.
"""
import re
from dataclasses import dataclass, field
from datetime import date

EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\U00002190-\U000021ff"
    "\U00002b00-\U00002bff\U0000fe0f\U0000200d]+"
)
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
MENTION_RE = re.compile(r"(?<!\w)@[\w.]+")
URL_RE = re.compile(r"https?://\S+", re.I)
LINK_IN_BIO_RE = re.compile(r"\blink\s+in\s+(my\s+)?bio\b", re.I)
IMAGE_RE = re.compile(r"\b(screenshot|screen ?shot|photo|picture|pic|image)\b|📸|🖼", re.I)
EMOTION_RE = re.compile(
    r"\b(shocking|outrage|outrageous|unbelievable|disgusting|terrifying|wake up|they don'?t want you to know|"
    r"share before|before they delete|must see|insane)\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


@dataclass
class Signals:
    has_source_link: bool = False
    link_in_bio: bool = False
    old_date: bool = False
    old_year: int | None = None
    image_mentioned: bool = False
    is_reel: bool = False
    emotional: bool = False
    many_hashtags: bool = False
    hashtag_count: int = 0
    extra: dict = field(default_factory=dict)


def strip_clutter(text: str) -> str:
    """Remove emojis, hashtags, @mentions and links; collapse whitespace."""
    text = URL_RE.sub(" ", text)
    text = EMOJI_RE.sub(" ", text)
    text = HASHTAG_RE.sub(" ", text)
    text = MENTION_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—|:")


def normalise_post(text: str, max_chars: int = 2000) -> str:
    return strip_clutter(text)[:max_chars].strip()


def detect_signals(text: str, *, post_date: date | None = None, is_reel: bool = False,
                   today: date | None = None) -> Signals:
    today = today or date.today()
    links = [u for u in URL_RE.findall(text) if "instagram.com" not in u.lower()]
    hashtags = HASHTAG_RE.findall(text)
    words = re.findall(r"[A-Za-z]{3,}", text)
    caps_words = [w for w in words if w.isupper() and len(w) >= 4]

    old_year = None
    if post_date and (today - post_date).days > 365:
        old_year = post_date.year
    else:
        years = [int(y) for y in YEAR_RE.findall(text)]
        past = [y for y in years if y <= today.year - 2]
        if past:
            old_year = min(past)

    return Signals(
        has_source_link=bool(links),
        link_in_bio=bool(LINK_IN_BIO_RE.search(text)),
        old_date=old_year is not None,
        old_year=old_year,
        image_mentioned=bool(IMAGE_RE.search(text)),
        is_reel=is_reel,
        emotional=bool(EMOTION_RE.search(text)) or len(caps_words) >= 2 or "!!!" in text,
        many_hashtags=len(hashtags) >= 4,
        hashtag_count=len(hashtags),
    )
