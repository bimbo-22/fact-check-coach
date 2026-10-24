"""Hallucination safeguard: an LLM label only counts if its quote is really in the source text."""
import logging
import re
import unicodedata

from rapidfuzz import fuzz

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 90  # rapidfuzz partial_ratio, 0–100 (spec: ratio ≥ 0.9)
MIN_QUOTE_CHARS = 15  # a two-word "quote" proves nothing

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_TRANSLATE).lower()
    return re.sub(r"\s+", " ", s).strip()


def quote_in_text(quote: str | None, text: str) -> bool:
    if not quote:
        return False
    q, t = normalise(quote), normalise(text)
    if len(q) < MIN_QUOTE_CHARS:
        return False
    if q in t:
        return True
    return fuzz.partial_ratio(q, t) >= FUZZY_THRESHOLD


def verify_label(stance: str, quote: str | None, text: str, domain: str = "") -> tuple[str, str | None, bool]:
    """Return (stance, quote, rejected). Unsupported labels are downgraded to not_mentioned."""
    if stance == "not_mentioned":
        return "not_mentioned", None, False
    if quote_in_text(quote, text):
        return stance, quote.strip() if quote else None, False
    log.warning("rejected hallucinated quote: stance=%s domain=%s", stance, domain)
    return "not_mentioned", None, True
